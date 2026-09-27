"""Exercise repository filters against a real, isolated SQL database."""

import unittest
import uuid
from datetime import datetime, timedelta

from sqlmodel import SQLModel, Session, create_engine

from app.models.user import UserTable  # noqa: F401  (register the foreign-key target)
from app.models.analysis import Analysis
from app.infrastructure.database.repositories import AnalysisRepository


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)


class AnalysisRepositoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = AnalysisRepository(AsyncSessionAdapter(self.session))
        self.owner, self.other = uuid.uuid4(), uuid.uuid4()
        now = datetime.utcnow()
        self.records = [
            Analysis(user_id=self.owner, task_type="leaf", status="completed", created_at=now),
            Analysis(user_id=self.owner, task_type="stem", status="failed", created_at=now - timedelta(days=1)),
            Analysis(user_id=self.other, task_type="leaf", status="completed", created_at=now),
        ]
        self.session.add_all(self.records)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    async def test_single_record_cannot_cross_user_boundary(self):
        foreign_id = self.records[2].analysis_id
        self.assertIsNone(await self.repo.get(foreign_id, self.owner))
        self.assertEqual((await self.repo.get(self.records[0].analysis_id, self.owner)).user_id, self.owner)

    async def test_history_is_scoped_and_sorted(self):
        records = await self.repo.list(self.owner)
        self.assertEqual([r.analysis_id for r in records], [r.analysis_id for r in self.records[:2]])

    async def test_http_string_ids_work_with_uuid_columns(self):
        record = await self.repo.get(str(self.records[0].analysis_id), self.owner)
        self.assertEqual(record.analysis_id, self.records[0].analysis_id)
        rows = await self.repo.list(self.owner, analysis_ids=[str(record.analysis_id)])
        self.assertEqual([r.analysis_id for r in rows], [record.analysis_id])

    async def test_empty_filters_never_expand_to_all_records(self):
        self.assertEqual(await self.repo.list(self.owner, task_types=[]), [])
        self.assertEqual(await self.repo.list(self.owner, analysis_ids=[]), [])

    async def test_batch_export_combines_owner_status_and_ids(self):
        records = await self.repo.list(self.owner, analysis_ids=[r.analysis_id for r in self.records], status="completed")
        self.assertEqual([r.analysis_id for r in records], [self.records[0].analysis_id])
