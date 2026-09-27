"""Export workflows shared by the HTTP routers."""
import os
import io
import json
import base64
import logging
from datetime import datetime
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from app.features.export.excel import excel_service
from app.features.task_catalog.catalog import normalize_task_type
from app.infrastructure.storage.results import read_json

log = logging.getLogger(__name__)


def get_json_data(json_path):
    """读取JSON文件内容"""
    return read_json(json_path)


def export_json_response(json_path, filename=None):
    """将JSON文件转换为可下载的响应"""
    data = get_json_data(json_path)
    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    if filename is None:
        filename = os.path.basename(json_path)
    if not filename.endswith('.json'):
        filename = filename + '.json'

    return StreamingResponse(
        io.BytesIO(json_str.encode('utf-8')),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename={}".format(filename),
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


async def export_all_analysis_to_excel(request_data, user, repository):
    try:
        selected_columns = request_data.selectedColumns
        unit = request_data.unit
        scale = request_data.scale
        task_type = normalize_task_type(request_data.taskType or "stem")
        log.info(f"用户 {user.id} 请求导出所有分析记录（类型: {task_type}），选择的列: {selected_columns}，单位: {unit}，比例尺: {scale}")

        all_analyses = await repository.list(user.id, task_type=task_type, status="completed")

        if not all_analyses:
            raise HTTPException(status_code=404, detail="没有找到已完成的分析记录")

        log.info(f"找到 {len(all_analyses)} 个已完成的分析记录")

        valid_analysis_data = []
        for analysis in all_analyses:
            try:
                analysis_data = excel_service.load_record_data(analysis, str(user.id), unit, scale, task_type)
                valid_analysis_data.append(analysis_data)
                log.debug(f"成功加载分析数据: {analysis.analysis_id}")
            except Exception as e:
                log.warning(f"加载分析数据失败 {analysis.analysis_id}: {e}")
                continue

        if not valid_analysis_data:
            raise HTTPException(status_code=404, detail="没有成功加载任何分析数据")

        log.info(f"成功加载 {len(valid_analysis_data)} 个分析任务的数据")

        excel_file = excel_service.export_all_to_excel(valid_analysis_data, selected_columns, task_type)

        log.info(f"所有分析记录Excel文件生成成功，包含 {len(valid_analysis_data)} 个样本")

        return {
            "filename": f"{len(valid_analysis_data)}条记录_{datetime.now().strftime('%Y.%m.%d_%H:%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "total_samples": len(valid_analysis_data),
            "task_type": task_type,
            "message": f"成功导出 {len(valid_analysis_data)} 个分析记录"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出所有分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"导出所有分析记录失败: {str(e)}")


async def export_batch_to_excel(request_data, user, repository):
    try:
        analysis_ids = request_data.analysisIds
        selected_columns = request_data.selectedColumns
        unit = request_data.unit
        scale = request_data.scale
        log.info(f"用户 {user.id} 请求批量导出 {len(analysis_ids)} 个分析记录，选择的列: {selected_columns}")

        analyses = await repository.list(user.id, analysis_ids=analysis_ids, status="completed", ordered=False)

        if not analyses:
            raise HTTPException(status_code=404, detail="没有找到有效的已完成分析记录")

        # 批量导出要求同一分析类型：不同类型列口径不同，混在一张表里没有意义
        task_types = {(a.task_type or "stem") for a in analyses}
        if len(task_types) > 1:
            raise HTTPException(
                status_code=400,
                detail=f"所选记录包含多种分析类型（{sorted(task_types)}），请按类型分别导出"
            )
        task_type = normalize_task_type(task_types.pop())

        valid_analysis_data = []
        for analysis in analyses:
            try:
                analysis_data = excel_service.load_record_data(analysis, str(user.id), unit, scale, task_type)
                valid_analysis_data.append(analysis_data)
            except Exception as e:
                log.warning(f"批量导出中加载分析数据失败 {analysis.analysis_id}: {e}")
                continue

        if not valid_analysis_data:
            raise HTTPException(status_code=404, detail="没有成功加载任何分析数据")

        excel_file = excel_service.export_all_to_excel(valid_analysis_data, selected_columns, task_type)

        log.info(f"批量导出Excel成功，包含 {len(valid_analysis_data)} 个样本")

        return {
            "filename": f"批量导出_{len(valid_analysis_data)}条_{datetime.now().strftime('%Y.%m.%d_%H:%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "total_samples": len(valid_analysis_data),
            "message": f"成功导出 {len(valid_analysis_data)} 个分析记录"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"批量导出Excel时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"批量导出失败: {str(e)}")


async def export_analysis_to_excel(analysis_id, request_data, user, repository):
    try:
        selected_columns = request_data.selectedColumns
        unit = request_data.unit
        scale = request_data.scale
        log.info(f"用户 {user.id} 请求导出分析结果 {analysis_id}，选择的列: {selected_columns}，单位: {unit}，比例尺: {scale}")

        analysis = await repository.get(analysis_id, user.id)

        if not analysis:
            log.warning(f"分析记录 {analysis_id} 不存在或不属于用户 {user.id}")
            raise HTTPException(status_code=404, detail="分析记录不存在")

        if analysis.status != "completed":
            log.warning(f"分析记录 {analysis_id} 状态为 {analysis.status}，无法导出")
            raise HTTPException(status_code=400, detail="分析记录尚未完成，无法导出")

        task_type = normalize_task_type(analysis.task_type or "stem")

        analysis_data = excel_service.load_record_data(analysis, str(user.id), unit, scale, task_type)

        df = excel_service.generate_excel_data(analysis_data, selected_columns, task_type)

        excel_file = excel_service.create_excel_file(df)

        log.info(f"分析记录 {analysis_id} Excel文件生成成功")

        return {
            "filename": f"{analysis_id}_{datetime.now().strftime('%Y.%m.%d_%H:%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "message": "分析记录导出成功"
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出分析记录时发生错误 {e}")
        raise HTTPException(status_code=500, detail=f"导出分析记录失败: {str(e)}")


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

        # ✅ 修复：使用 original_file_path 提取文件名
        original_name = os.path.splitext(os.path.basename(analysis.original_file_path))[0]
        filename = "{}_analysis.json".format(original_name)

        return export_json_response(
            json_path=analysis.result_json_path,
            filename=filename
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
                # ✅ 修复：使用 basename 提取文件名
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

        analyses = await repository.list(user.id, analysis_ids=analysis_ids, status="completed", ordered=False)

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
                    # ✅ 修复：使用 basename 提取文件名
                    'name': "{}.json".format(os.path.splitext(os.path.basename(analysis.original_file_path))[0])
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

        zip_filename = "batch_export_{}files_{}.zip".format(
            len(json_files),
            datetime.now().strftime('%Y%m%d_%H%M%S')
        )

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename={}".format(zip_filename)
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



class ExportService:
    """Compatibility facade for scripts that use the former service object."""
    get_json_data = staticmethod(get_json_data)
    get_json_statistics = staticmethod(get_json_statistics)
    _format_size = staticmethod(_format_size)

    def export_json_response(self, json_path, filename=None):
        response = export_json_response(json_path, filename)
        response.media_type = "application/json"
        response.headers["content-type"] = "application/json"
        return response

    def _extract_labels(self, data):
        counts = {}
        for shape in data.get("shapes", []):
            label = shape.get("label", "unknown")
            counts[label] = counts.get(label, 0) + 1
        return counts


export_service = ExportService()
