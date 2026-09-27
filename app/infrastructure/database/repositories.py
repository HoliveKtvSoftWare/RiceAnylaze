"""User-scoped analysis persistence shared by history, deletion and export."""

from typing import Dict, List, Optional, Sequence
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.analysis import Analysis
from app.models.batch import UploadBatch


class AnalysisRepository:
    """User-scoped async access to analysis records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, analysis_id: UUID, user_id: UUID) -> Optional[Analysis]:
        statement = select(Analysis).where(
            Analysis.analysis_id == UUID(str(analysis_id)),
            Analysis.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return result.scalars().one_or_none()

    async def list(
        self,
        user_id: UUID,
        task_type: Optional[str] = None,
        task_types: Optional[List[str]] = None,
        analysis_ids: Optional[Sequence] = None,
        status: Optional[str] = None,
        statuses: Optional[List[str]] = None,
        ordered: bool = True,
        offset=None,
        limit=None,
    ) -> List[Analysis]:
        statement = select(Analysis).where(Analysis.user_id == user_id)
        if task_type is not None:
            statement = statement.where(Analysis.task_type == task_type)
        elif task_types is not None:
            statement = statement.where(Analysis.task_type.in_(task_types))
        if analysis_ids is not None:
            statement = statement.where(Analysis.analysis_id.in_([UUID(str(value)) for value in analysis_ids]))
        if status:
            statement = statement.where(Analysis.status == status)
        elif statuses is not None:
            statement = statement.where(Analysis.status.in_(statuses))
        if ordered:
            statement = statement.order_by(Analysis.created_at.desc())
        if offset is not None:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def save(self, record):
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)

    async def delete(self, record):
        await self.session.delete(record)

    async def commit(self):
        await self.session.commit()


class SyncAnalysisRepository:
    """Compatibility access for synchronous export scripts."""

    def __init__(self, session):
        self.session = session

    def get(self, analysis_id, user_id):
        statement = select(Analysis).where(
            Analysis.analysis_id == UUID(str(analysis_id)),
            Analysis.user_id == UUID(str(user_id)),
        )
        return self.session.exec(statement).one_or_none()


class BatchRepository:
    """User-scoped access to upload batches（批次名与批次复用）。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, batch_id, user_id) -> Optional[UploadBatch]:
        statement = select(UploadBatch).where(
            UploadBatch.batch_id == UUID(str(batch_id)),
            UploadBatch.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return result.scalars().one_or_none()

    async def names_for(self, user_id, batch_ids: Sequence) -> Dict[UUID, str]:
        """一次查出多个批次名，供历史列表拼装 ``batchName``（避免 N+1 查询）。"""
        ids = [UUID(str(value)) for value in batch_ids if value]
        if not ids:
            return {}
        statement = select(UploadBatch).where(
            UploadBatch.user_id == user_id,
            UploadBatch.batch_id.in_(ids),
        )
        result = await self.session.execute(statement)
        return {row.batch_id: row.name for row in result.scalars().all() if row.name}


__all__ = ["AnalysisRepository", "SyncAnalysisRepository", "BatchRepository"]
