"""Analysis HTTP contracts; workflows live in the analysis feature."""
from fastapi import APIRouter, Depends, UploadFile, File, Body, Form, Request
from typing import List, Dict, Any, Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.user import UserTable
from app.api.deps import current_active_user, get_async_session
from app.infrastructure.database.repositories import AnalysisRepository
from app.features.analysis import history_service, statistics_service, file_service

router = APIRouter()

@router.get("/models")
async def get_available_models(
    group: Optional[str] = None,
    user: UserTable = Depends(current_active_user)
):
    """新版前端的模型选择器数据源："分析类型（模型）"下拉框。

    返回 ``{"models": [{"name", "path", "key", "group"}], "default": name}``。
    前端的 select 把 ``name`` 同时当作 value 和展示文本，并在上传时原样作为
    ``model_name`` 回传；后端用 ``resolve_task_type`` 把它解析回 task key。

    可选参数 group：按大类过滤（stem=茎秆 / leaf=剑叶），不传时返回全部。
    """
    return await history_service.get_available_models(group=group)


@router.get("/tasks")
async def get_analysis_tasks(
    group: Optional[str] = None,
    user: UserTable = Depends(current_active_user)
):
    """
    返回系统支持的分析类型（模型）列表，供前端渲染"分析类型"下拉框。

    可选参数 group：按大类过滤（stem=茎秆 / leaf=剑叶），不传时返回全部。
    """
    return await history_service.get_analysis_tasks(group=group, user=user)


@router.get("/history")
async def get_analysis_history(
    request: Request,
    task_type: Optional[str] = None,
    group: Optional[str] = None,
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> List[Dict[str, Any]]:
    """
    获取当前登录用户的分析历史记录，包含可访问的文件 URL。

    分域参数（二选一，同时传时 task_type 优先）：
      task_type: 精确到某个分析类型（如 leaf_our）
      group:     整个大类（stem=茎秆 / leaf=剑叶），用于"茎秆分析 / 剑叶分析"两个页面
    都不传时返回全部记录（主页的近期记录用）。
    """
    return await history_service.get_analysis_history(request=request, task_type=task_type, group=group, user=user, repository=AnalysisRepository(db))


@router.get("/stats")
async def get_analysis_stats(
    days: int = 7,
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> Dict[str, Any]:
    """主页统计：总览计数、近 N 天完成趋势与平均推理耗时。

    days：趋势窗口（1~90，默认 7）。
    耗时为 finished_at - started_at，只统计两者都有的记录（老记录没有，自动跳过）。
    时间一律按 UTC 比较，按"北京时区（UTC+8）"切成自然日展示。
    """
    return await statistics_service.get_analysis_stats(days=days, user=user, repository=AnalysisRepository(db))


@router.get("/queue")
async def get_analysis_queue(
    user: UserTable = Depends(current_active_user),
) -> Dict[str, Any]:
    """分析队列概况：正在执行的任务与排队中的任务。

    后端是**单 worker 串行**执行（一次只跑一张图），因此 `pendingCount`
    就是"前面还有几张在等"。前端据此区分"排队中"和"正在处理"。
    """
    return await file_service.get_analysis_queue(user=user)


@router.post("/upload")
async def upload_image(
    file: UploadFile = File(...),
    task_type: str = Form("stem"),
    model_name: Optional[str] = Form(None),
    batch_id: Optional[str] = Form(None),
    batch_name: Optional[str] = Form(None),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    接收用户上传：保存文件，创建记录，排入分析队列（串行执行）。
    单文件上传时自动创建批次。

    分析类型二选一（同时传时 model_name 优先）：
      model_name: 新版前端从 /analysis/models 拿到并回传的模型名（key 或中文显示名）
      task_type:  分析类型 key（stem=茎秆截面，默认 / leaf=剑叶），未知值回退为 stem

    batch_id / batch_name：前端一次"选择多张单图"会把同一个 batch_id 发给每张图，
    后端复用它，使这批图在历史里归为同一批次；批次名用于前端展示。
    """
    return await file_service.upload_image(
        file=file, task_type=task_type, model_name=model_name,
        batch_id=batch_id, batch_name=batch_name,
        user=user, repository=AnalysisRepository(db))


@router.post("/upload/batch")
async def upload_images_batch(
    files: List[UploadFile] = File(...),
    task_type: str = Form("stem"),
    model_name: Optional[str] = Form(None),
    batch_id: Optional[str] = Form(None),
    batch_name: Optional[str] = Form(None),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    批量上传图片：创建批次，保存文件，创建记录，**按顺序**排入分析队列。

    与逐个上传的区别：一次请求建一个批次、写 1 次批次记录，
    并且这 N 张图会连续排在队列里依次执行（单 worker，不会并发跑）。

    分析类型二选一（同时传时 model_name 优先）：model_name / task_type；
    整批使用同一类型。batch_name 为该批次展示名（如文件夹名）。
    """
    return await file_service.upload_images_batch(
        files=files, task_type=task_type, model_name=model_name,
        batch_id=batch_id, batch_name=batch_name,
        user=user, repository=AnalysisRepository(db))


@router.delete("/delete/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    删除指定的分析记录
    """
    return await file_service.delete_analysis(analysis_id=analysis_id, user=user, repository=AnalysisRepository(db))


@router.post("/delete/batch")
async def delete_analyses_batch(
    request_data: Dict[str, List[str]] = Body(...),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    批量删除分析记录
    请求体: { "analysisIds": ["id1", "id2", "id3"] }
    """
    return await file_service.delete_analyses_batch(request_data=request_data, user=user, repository=AnalysisRepository(db))
