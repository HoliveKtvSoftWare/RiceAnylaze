"""User history queries, task selection and history response assembly."""
import os
import logging
from fastapi import HTTPException
from app.features.task_catalog import (
    is_valid_task_group, task_types_of_group, list_tasks,
    list_models, default_model_name, get_task, get_tasks, TASK_GROUPS,
)
from app.infrastructure.database.repositories import BatchRepository
from app.infrastructure.storage.files import path_to_static_url, original_filename
from app.infrastructure.storage.previews import ensure_preview_cached

log = logging.getLogger(__name__)


async def get_available_models(group=None):
    """新版前端模型选择器的数据源（``GET /analysis/models``）。

    前端把返回的 ``name`` 同时当作 select 的 value 与展示文本，并在上传时
    原样作为 ``model_name`` 回传；后端用 ``resolve_task_type`` 解析回 task key。

    可选参数 group：按大类过滤（stem=茎秆 / leaf=剑叶），不传时返回全部
    （stem 排在最前，作为默认）。
    """
    if group and not is_valid_task_group(group):
        raise HTTPException(status_code=400, detail=f"未知的分析大类 '{group}'，应为 stem 或 leaf")
    return {
        "models": list_models(group),
        "default": default_model_name(group),
    }


async def get_analysis_tasks(group, user):
    """
    返回系统支持的分析类型（模型）列表，供前端渲染"分析类型"下拉框。

    可选参数 group：按大类过滤（stem=茎秆 / leaf=剑叶），不传时返回全部。
    """
    if group and not is_valid_task_group(group):
        raise HTTPException(status_code=400, detail=f"未知的分析大类 '{group}'，应为 stem 或 leaf")
    return {"tasks": list_tasks(group)}


async def get_analysis_history(request, task_type, group, user, repository):
    """
    获取当前登录用户的分析历史记录，包含可访问的文件 URL。

    分域参数（二选一，同时传时 task_type 优先）：
      task_type: 精确到某个分析类型（如 leaf_our）
      group:     整个大类（stem=茎秆 / leaf=剑叶），用于"茎秆分析 / 剑叶分析"两个页面
    都不传时返回全部记录（主页的近期记录用）。
    """
    log.info(f"用户 {user.id} 请求分析历史记录... task_type={task_type} group={group}")
    group_types = None
    if not task_type and group:
        if not is_valid_task_group(group):
            raise HTTPException(status_code=400, detail=f"未知的分析大类 '{group}'，应为 stem 或 leaf")
        group_types = task_types_of_group(group) or []
    history_records = await repository.list(
        user.id, task_type=task_type.strip().lower() if task_type else None, task_types=group_types,
    )

    log.info(f"为用户 {user.id} 找到 {len(history_records)} 条历史记录。")

    # 批次名一次查全，避免逐条查库
    batch_names = await BatchRepository(repository.session).names_for(
        user.id, [record.batch_id for record in history_records]
    )

    # 任务 -> 所属族。一次建表，避免每条记录都重建注册表。
    # 前端据此把记录归到"茎秆 / 剑叶"页并选择对应的导出列，
    # 不必自己用 task_type 猜族（新增族时前端零改动）。
    tasks = get_tasks()
    task_groups = {spec.key: spec.group for spec in tasks.values()}
    default_task_type = get_task(None).key
    default_group = get_task(None).group

    base_url = str(request.base_url)
    history_with_urls = []
    for record in history_records:
        def path_to_url(path):
            return path_to_static_url(path, base_url)

        display_filename = original_filename(record.original_file_path)

        # 原图多为 .tif/.tiff，浏览器不能直接渲染：优先返回同目录的 JPEG 预览图。
        # 预览在"上传时"生成；这里对缺失的预览做一次按需兜底（含失败负缓存，
        # 不会在 2 秒一次的轮询里反复解码同一张坏图），补不回来才回退原图 URL
        # （前端对 TIFF 会显示"无法预览 + 下载"的提示）。
        original_display_path = record.original_file_path
        if record.original_file_path and os.path.exists(record.original_file_path):
            original_display_path = (ensure_preview_cached(record.original_file_path)
                                     or record.original_file_path)

        history_with_urls.append({
            "analysisId": record.analysis_id,
            "taskType": record.task_type or default_task_type,
            "group": task_groups.get((record.task_type or "").strip().lower(), default_group),
            "batchId": str(record.batch_id) if record.batch_id else None,
            "batchIndex": record.batch_index,
            "batchName": batch_names.get(record.batch_id),
            "createdAt": record.created_at,
            "startedAt": record.started_at,
            "finishedAt": record.finished_at,
            "status": record.status,
            "modelUsed": record.model_used,
            "errorMessage": record.error_message,
            "originalFilename": display_filename,
            "originalImageUrl": path_to_url(original_display_path),
            "originalFileUrl": path_to_url(record.original_file_path),
            "annotatedImageUrl": path_to_url(record.annotated_image_path),
            "resultJsonUrl": path_to_url(record.result_json_path),
        })

    return history_with_urls
