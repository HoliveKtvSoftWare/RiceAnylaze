"""Excel export HTTP contracts; workflows live in app.features.export."""
from fastapi import APIRouter, Depends, Body
from sqlmodel.ext.asyncio.session import AsyncSession
from app.api.deps import current_active_user, get_async_session
from app.models.user import UserTable
from app.infrastructure.database.repositories import AnalysisRepository
from app.features.export import service
from app.features.export.schemas import ExportRequest, BatchExportRequest

router = APIRouter()


@router.get("/columns")
async def get_export_columns(task_type: str = "stem"):
    """
    按分析类型返回可导出的列配置。

    task_type: stem=茎秆截面（默认，兼容旧调用）/ leaf=剑叶。
    新版前端不带参数调用，拿默认的 stem 列。
    """
    return await service.get_export_columns(task_type=task_type)


@router.post("/summary")
async def export_all_analysis_to_excel(
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    """
    汇总导出：默认导出当前用户全部已完成记录（记录类型需一致）。

    同步返回 xlsx 字节流；``asyncMode=true`` 时返回
    ``{taskId, pollUrl, downloadUrl}``，由前端轮询 /tasks/{id}。
    """
    return await service.export_all_analysis_to_excel(
        request_data=request_data, user=user, repository=AnalysisRepository(db))


@router.post("/batch")
async def export_batch_to_excel(
        request_data: BatchExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    """
    批量导出：传 analysisIds，或 allCompleted=true 导出全部已完成记录。
    同步/异步与 /summary 一致。
    """
    return await service.export_batch_to_excel(
        request_data=request_data, user=user, repository=AnalysisRepository(db))


@router.get("/tasks/{task_id}")
async def get_export_task_status(task_id: str, user: UserTable = Depends(current_active_user)):
    """查询异步导出任务的进度（status: processing / completed / failed）。"""
    return service.get_task_status(task_id)


@router.get("/download/{task_id}")
async def download_export_task(task_id: str, user: UserTable = Depends(current_active_user)):
    """下载异步导出任务的结果（xlsx）。"""
    return service.download_task_result(task_id)


@router.post("/{analysis_id}")
async def export_analysis_to_excel(
        analysis_id: str,
        request_data: ExportRequest = Body(...),
        user: UserTable = Depends(current_active_user),
        db: AsyncSession = Depends(get_async_session)
):
    """单条导出：直接返回 xlsx 字节流，文件名由后端给出。"""
    return await service.export_analysis_to_excel(
        analysis_id=analysis_id, request_data=request_data,
        user=user, repository=AnalysisRepository(db))
