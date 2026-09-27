"""Export workflows shared by the HTTP routers.

同步路径直接返回 xlsx 字节流（前端 axios 用 responseType:'blob' 接）；
记录较多时前端传 ``asyncMode=true``，这里改成提交后台任务并返回 taskId，
具体状态在 :mod:`app.features.export.tasks` 里维护。
"""
import os
import io
import re
import json
import logging
from datetime import datetime
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from app.features.export import responses, tasks
from app.features.export.excel import excel_service
from app.features.task_catalog.catalog import (
    normalize_task_type, schema_of, task_keys_of_schema,
)
from app.infrastructure.storage.results import read_json

log = logging.getLogger(__name__)


def _extract_real_name(original_file_path: str) -> str:
    """从 ``<uuid>_<原名>_<YYYYMMDD_HHMMSS>.<ext>`` 还原用户看到的样本名。"""
    basename = os.path.basename(original_file_path or "")
    parts = basename.split('_', 1)
    if len(parts) == 2 and len(parts[0]) == 36:
        name_with_ext = parts[1]
    else:
        name_with_ext = basename
    name_no_ext = os.path.splitext(name_with_ext)[0]
    return re.sub(r'_\d{8}_\d{6}$', '', name_no_ext)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_json_data(json_path):
    """读取JSON文件内容"""
    return read_json(json_path)


def export_json_response(json_path, download_name=None):
    """将JSON文件转换为可下载的响应"""
    data = get_json_data(json_path)
    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    if not download_name:
        download_name = os.path.basename(json_path)
    if not download_name.endswith('.json'):
        download_name = download_name + '.json'

    return StreamingResponse(
        io.BytesIO(json_str.encode('utf-8')),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": responses.build_content_disposition(download_name),
            "Content-Length": str(len(json_str))
        }
    )


def get_json_statistics(json_path):
    """获取JSON文件的统计信息"""
    try:
        data = get_json_data(json_path)
        file_stat = os.stat(json_path)

        label_counts = {}
        for shape in data.get('shapes', []):
            label = shape.get('label', 'unknown')
            label_counts[label] = label_counts.get(label, 0) + 1

        return {
            'filename': os.path.basename(json_path),
            'file_size': file_stat.st_size,
            'file_size_human': _format_size(file_stat.st_size),
            'modified_time': datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
            'shapes_count': len(data.get('shapes', [])),
            'labels': label_counts,
            'image_width': data.get('imageWidth', 0),
            'image_height': data.get('imageHeight', 0),
        }
    except Exception as e:
        return {'error': str(e)}


def _format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 1024:
        return "{} B".format(size_bytes)
    elif size_bytes < 1024 * 1024:
        return "{:.1f} KB".format(size_bytes / 1024)
    else:
        return "{:.1f} MB".format(size_bytes / (1024 * 1024))


async def get_export_columns(task_type):
    """
    按分析类型返回可导出的列配置。
    task_type: stem=茎秆截面（默认，兼容旧调用）/ leaf=剑叶
    """
    normalized = normalize_task_type(task_type)
    return {
        "available_columns": excel_service.get_available_columns(normalized),
        "task_type": normalized,
        "message": "可导出的列配置"
    }


# --------------------------------------------------------------------------- #
# Excel 导出
# --------------------------------------------------------------------------- #
def _record_info(record, user_id, task_type):
    """在请求的 session 内把任务需要的最小字段取出来（线程里不再查库）。"""
    return {
        "analysis_id": str(record.analysis_id),
        "user_id": str(user_id),
        "original_file_path": record.original_file_path,
        "result_json_path": record.result_json_path,
        "task_type": record.task_type or task_type,
    }


def _export_task_type(records, requested):
    """导出用哪套列口径（列定义）。

    显式传了 taskType 就用它；否则按记录推断。注意归并的粒度是**口径**而不是
    精确 task key：``leaf`` / ``leaf_our`` 等共用 leaf 列定义，混在一起合法；
    而 stem 与 leaf 的列完全不同，混在一张表里没有意义，所以直接报 400。
    """
    if requested:
        return normalize_task_type(requested)
    schemas = {schema_of(record.task_type or "stem") for record in records}
    if len(schemas) > 1:
        raise HTTPException(
            status_code=400,
            detail="所选记录同时包含茎秆与剑叶（{}），两者的数据项不同，请分开导出".format(sorted(schemas))
        )
    return normalize_task_type(records[0].task_type or "stem")


def _load_valid(records, unit, scale, task_type):
    """逐条算指标，坏数据的记录跳过（不让一条坏记录毁掉整表）。"""
    valid = []
    for record in records:
        try:
            valid.append(excel_service.load_record_data(
                record, str(record.user_id), unit, scale, task_type))
        except Exception as e:
            log.warning(f"导出中跳过记录 {record.analysis_id}: {e}")
    return valid


def _sync_xlsx_response(records, selected_columns, unit, scale, task_type):
    valid = _load_valid(records, unit, scale, task_type)
    if not valid:
        raise HTTPException(status_code=404, detail="没有成功加载任何分析数据")

    buffer = excel_service.export_all_to_excel(valid, selected_columns, task_type)
    filename = "{}_{}个文件{}_{}.xlsx".format(
        tasks.label_prefix(task_type), len(valid), _timestamp(), unit)
    log.info(f"Excel 导出完成: {filename}（成功 {len(valid)}/{len(records)}）")
    return responses.xlsx_response(buffer.getvalue(), filename)


def _async_task_response(records, selected_columns, unit, scale, task_type, user):
    task_id = tasks.submit(
        [_record_info(record, user.id, task_type) for record in records],
        selected_columns, unit, scale, task_type,
    )
    return {
        "success": True,
        "message": "已提交后台导出任务，共 {} 条记录".format(len(records)),
        "taskId": task_id,
        "pollUrl": "/api/excel/tasks/{}".format(task_id),
        "downloadUrl": "/api/excel/download/{}".format(task_id),
    }


async def export_all_analysis_to_excel(request_data, user, repository):
    """汇总导出：当前用户的全部（或指定口径的）已完成记录。"""
    try:
        requested = normalize_task_type(request_data.taskType) if request_data.taskType else None
        if requested:
            # 按口径取：选了 leaf 就把 leaf / leaf_our … 一起汇总，而不是只要其中一个
            records = await repository.list(
                user.id, task_types=task_keys_of_schema(schema_of(requested)),
                status="completed",
            )
        else:
            records = await repository.list(user.id, status="completed")
        if not records:
            raise HTTPException(status_code=404, detail="没有找到已完成的分析记录")

        task_type = _export_task_type(records, request_data.taskType)
        log.info(f"用户 {user.id} 汇总导出：{len(records)} 条，类型 {task_type}，"
                 f"列 {request_data.selectedColumns}，单位 {request_data.unit}")

        if request_data.asyncMode:
            return _async_task_response(records, request_data.selectedColumns,
                                        request_data.unit, request_data.scale,
                                        task_type, user)

        return _sync_xlsx_response(records, request_data.selectedColumns,
                                   request_data.unit, request_data.scale, task_type)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出所有分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"导出所有分析记录失败: {str(e)}")


async def export_batch_to_excel(request_data, user, repository):
    """批量导出：按 id 列表，或 allCompleted=true 导出全部已完成记录。"""
    try:
        if request_data.allCompleted:
            records = await repository.list(user.id, status="completed")
        elif request_data.analysisIds:
            records = await repository.list(user.id, analysis_ids=request_data.analysisIds,
                                            status="completed", ordered=False)
        else:
            raise HTTPException(status_code=400, detail="请传入 analysisIds 或设置 allCompleted=true")

        if not records:
            raise HTTPException(status_code=404, detail="没有找到有效的已完成分析记录")

        task_type = _export_task_type(records, request_data.taskType)
        log.info(f"用户 {user.id} 批量导出 {len(records)} 条记录，类型 {task_type}")

        if request_data.asyncMode:
            return _async_task_response(records, request_data.selectedColumns,
                                        request_data.unit, request_data.scale,
                                        task_type, user)

        return _sync_xlsx_response(records, request_data.selectedColumns,
                                   request_data.unit, request_data.scale, task_type)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"批量导出Excel时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"批量导出失败: {str(e)}")


async def export_analysis_to_excel(analysis_id, request_data, user, repository):
    """单条导出：文件名里带上用户看到的样本名（4d380a0 起由后端命名）。"""
    try:
        analysis = await repository.get(analysis_id, user.id)
        if not analysis:
            log.warning(f"分析记录 {analysis_id} 不存在或不属于用户 {user.id}")
            raise HTTPException(status_code=404, detail="分析记录不存在")
        if analysis.status != "completed":
            raise HTTPException(status_code=400, detail="分析记录尚未完成，无法导出")

        task_type = normalize_task_type(analysis.task_type or "stem")
        analysis_data = excel_service.load_record_data(
            analysis, str(user.id), request_data.unit, request_data.scale, task_type)
        df = excel_service.generate_excel_data(
            analysis_data, request_data.selectedColumns, task_type)
        buffer = excel_service.create_excel_file(df)

        filename = "{}_{}_{}_{}.xlsx".format(
            tasks.label_prefix(task_type), _extract_real_name(analysis.original_file_path),
            _timestamp(), request_data.unit)
        log.info(f"分析记录 {analysis_id} 导出成功: {filename}")
        return responses.xlsx_response(buffer.getvalue(), filename)

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出分析记录时发生错误 {e}")
        raise HTTPException(status_code=500, detail=f"导出分析记录失败: {str(e)}")


def get_task_status(task_id):
    """异步导出任务的进度（前端每 1.5s 轮询一次）。"""
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")

    response = {
        "taskId": task_id,
        "status": task["status"],
        "total": task["total"],
        "progress": task["progress"],
        "createdAt": task["created_at"],
    }
    if task["status"] == "completed":
        response["downloadUrl"] = "/api/excel/download/{}".format(task_id)
        response["filename"] = task.get("filename")
    elif task["status"] == "failed":
        response["error"] = task.get("error", "未知错误")
    return response


def download_task_result(task_id):
    """下载已完成的异步导出结果。"""
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="导出任务不存在")
    if task["status"] != "completed":
        raise HTTPException(status_code=400,
                            detail=f"导出尚未完成，当前状态: {task['status']}")

    resolved = tasks.result(task_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="导出结果不可用")
    file_path, filename = resolved
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件已丢失或被清理")
    return responses.xlsx_file_response(file_path, filename or os.path.basename(file_path))


# --------------------------------------------------------------------------- #
# JSON 导出
# --------------------------------------------------------------------------- #
async def export_analysis_json(analysis_id, user, repository):
    """
    导出分析结果的JSON文件
    """
    try:
        log.info("用户 {} 请求导出JSON: {}".format(user.id, analysis_id))

        analysis = await repository.get(analysis_id, user.id)

        if not analysis:
            raise HTTPException(status_code=404, detail="分析记录不存在")

        if analysis.status != "completed":
            raise HTTPException(
                status_code=400,
                detail="分析尚未完成，当前状态: {}".format(analysis.status)
            )

        if not analysis.result_json_path or not os.path.exists(analysis.result_json_path):
            raise HTTPException(status_code=404, detail="JSON文件不存在")

        # 后端负责命名：样本名 + 导出时间，避免前端拿到 UUID 文件名
        download_name = "{}_{}.json".format(
            _extract_real_name(analysis.original_file_path), _timestamp())

        return export_json_response(
            json_path=analysis.result_json_path,
            download_name=download_name
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error("导出JSON失败: {}".format(e), exc_info=True)
        raise HTTPException(status_code=500, detail="导出失败: {}".format(str(e)))


async def preview_analysis_json(analysis_id, user, repository):
    """
    预览JSON内容（不下载）
    """
    try:
        log.info("用户 {} 请求预览JSON: {}".format(user.id, analysis_id))

        analysis = await repository.get(analysis_id, user.id)

        if not analysis:
            raise HTTPException(status_code=404, detail="分析记录不存在")

        if not analysis.result_json_path or not os.path.exists(analysis.result_json_path):
            raise HTTPException(status_code=404, detail="JSON文件不存在")

        data = get_json_data(analysis.result_json_path)
        stats = get_json_statistics(analysis.result_json_path)

        return JSONResponse({
            'success': True,
            'data': data,
            'statistics': stats,
            'analysis_info': {
                'analysis_id': analysis.analysis_id,
                'original_filename': os.path.basename(analysis.original_file_path),
                'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
                'status': analysis.status
            }
        })

    except HTTPException:
        raise
    except Exception as e:
        log.error("预览JSON失败: {}".format(e), exc_info=True)
        raise HTTPException(status_code=500, detail="预览失败: {}".format(str(e)))


async def list_exportable_analyses(user, repository, limit, offset, status):
    """
    获取可导出的分析列表
    """
    try:
        log.info("用户 {} 请求分析列表, status={}".format(user.id, status))

        analyses = await repository.list(
            user.id, status=status, statuses=None if status else ["completed", "failed"],
            limit=limit, offset=offset,
        )

        result_list = []
        for analysis in analyses:
            json_exists = False
            json_size = None
            if analysis.result_json_path and os.path.exists(analysis.result_json_path):
                json_exists = True
                json_size = os.path.getsize(analysis.result_json_path)

            result_list.append({
                'analysis_id': analysis.analysis_id,
                'original_filename': os.path.basename(analysis.original_file_path),
                'original_file_path': analysis.original_file_path,
                'annotated_image_path': analysis.annotated_image_path,
                'result_json_path': analysis.result_json_path,
                'status': analysis.status,
                'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
                'updated_at': analysis.updated_at.isoformat() if analysis.updated_at else None,
                'json_exists': json_exists,
                'json_size': json_size,
                'json_size_human': _format_size(json_size) if json_size else None
            })

        return {
            'success': True,
            'data': result_list,
            'total': len(result_list),
            'limit': limit,
            'offset': offset
        }

    except Exception as e:
        log.error("获取列表失败: {}".format(e), exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


async def export_batch_json(analysis_ids_query, request_data, user, repository):
    """
    批量导出多个分析结果的JSON文件（返回ZIP压缩包）
    支持两种调用方式：
    1. Query 参数: POST /json/batch?analysis_ids=id1&analysis_ids=id2
    2. Body JSON:  { "analysisIds": ["id1", "id2"] }
    """
    import zipfile

    if request_data and request_data.analysisIds:
        analysis_ids = request_data.analysisIds
    elif analysis_ids_query:
        analysis_ids = analysis_ids_query
    else:
        raise HTTPException(status_code=422, detail="请通过 query(analysis_ids) 或 body(analysisIds) 传入要导出的ID列表")

    try:
        log.info("用户 {} 请求批量导出: {} 个文件".format(user.id, len(analysis_ids)))

        analyses = await repository.list(user.id, analysis_ids=analysis_ids,
                                         status="completed", ordered=False)

        if not analyses:
            raise HTTPException(
                status_code=404,
                detail="未找到有效的分析记录"
            )

        json_files = []
        for analysis in analyses:
            if analysis.result_json_path and os.path.exists(analysis.result_json_path):
                json_files.append({
                    'path': analysis.result_json_path,
                    'name': "{}.json".format(_extract_real_name(analysis.original_file_path))
                })

        if not json_files:
            raise HTTPException(
                status_code=404,
                detail="没有可导出的JSON文件"
            )

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_info in json_files:
                zipf.write(file_info['path'], file_info['name'])

        zip_buffer.seek(0)

        zip_filename = "{}个文件_{}.zip".format(len(json_files), _timestamp())

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": responses.build_content_disposition(zip_filename)
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error("批量导出失败: {}".format(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="批量导出失败: {}".format(str(e))
        )
