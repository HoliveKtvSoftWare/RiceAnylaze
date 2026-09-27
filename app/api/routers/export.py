"""JSON export HTTP contracts."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import current_active_user, get_async_session
from app.infrastructure.database.repositories import AnalysisRepository
from app.features.export import service
from app.features.export.schemas import BatchJsonExportRequest

router = APIRouter(prefix="/api/export", tags=["Export"])


@router.get("/json/{analysis_id}")
async def export_analysis_json(
    analysis_id,
    user=Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    """
    导出分析结果的JSON文件
    """
    return await service.export_analysis_json(analysis_id=analysis_id, user=user, repository=AnalysisRepository(session))


@router.get("/json/preview/{analysis_id}")
async def preview_analysis_json(
    analysis_id,
    user=Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    """
    预览JSON内容（不下载）
    """
    return await service.preview_analysis_json(analysis_id=analysis_id, user=user, repository=AnalysisRepository(session))


@router.get("/list")
async def list_exportable_analyses(
    user=Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
    limit=50,
    offset=0,
    status=None
):
    """
    获取可导出的分析列表
    """
    return await service.list_exportable_analyses(user=user, repository=AnalysisRepository(session), limit=limit, offset=offset, status=status)


@router.post("/json/batch")
async def export_batch_json(
    analysis_ids_query: Optional[List[str]] = Query(None, alias="analysis_ids"),
    request_data: Optional[BatchJsonExportRequest] = Body(default=None),
    user=Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session)
):
    """
    批量导出多个分析结果的JSON文件（返回ZIP压缩包）
    支持两种调用方式：
    1. Query 参数: POST /json/batch?analysis_ids=id1&analysis_ids=id2
    2. Body JSON:  { "analysisIds": ["id1", "id2"] }
    """
    return await service.export_batch_json(analysis_ids_query=analysis_ids_query, request_data=request_data, user=user, repository=AnalysisRepository(session))
