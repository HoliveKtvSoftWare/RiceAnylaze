"""Excel export HTTP contracts."""
from fastapi import APIRouter, Depends, Body
from sqlmodel.ext.asyncio.session import AsyncSession
from app.api.deps import current_active_user, get_async_session
from app.models.user import UserTable
from app.infrastructure.database.repositories import AnalysisRepository
from app.features.export import service
from app.features.export.excel import excel_service
from app.features.export.schemas import ExportRequest, BatchExportRequest

router = APIRouter()

@router.get("/columns")
async def get_export_columns(task_type: str = "stem"):
    """
    按分析类型返回可导出的列配置。
    task_type: stem=茎秆截面（默认，兼容旧调用）/ leaf=剑叶
    """
    return await service.get_export_columns(task_type=task_type)


@router.post("/summary")
async def export_all_analysis_to_excel(
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    return await service.export_all_analysis_to_excel(request_data=request_data, user=user, repository=AnalysisRepository(db))


@router.post("/batch")
async def export_batch_to_excel(
        request_data: BatchExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    return await service.export_batch_to_excel(request_data=request_data, user=user, repository=AnalysisRepository(db))


@router.post("/{analysis_id}")
async def export_analysis_to_excel(
        analysis_id: str,
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    return await service.export_analysis_to_excel(analysis_id=analysis_id, request_data=request_data, user=user, repository=AnalysisRepository(db))
