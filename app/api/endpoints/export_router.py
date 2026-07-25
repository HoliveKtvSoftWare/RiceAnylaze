"""
导出API端点 - 异步版本
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
import os
import json
import logging
from datetime import datetime
import io

from app.database.session import get_async_session
from app.models.analysis import Analysis
from app.auth.core import fastapi_users

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["Export"])


# ==================== 辅助服务函数 ====================

def get_json_data(json_path):
    """读取JSON文件内容"""
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


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


# ==================== API 端点 ====================

@router.get("/json/{analysis_id}")
async def export_analysis_json(
    analysis_id,
    user=Depends(fastapi_users.current_user(active=True)),
    session: AsyncSession = Depends(get_async_session)
):
    """
    导出分析结果的JSON文件
    """
    try:
        log.info("用户 {} 请求导出JSON: {}".format(user.id, analysis_id))

        statement = select(Analysis).where(
            Analysis.analysis_id == analysis_id,
            Analysis.user_id == user.id
        )
        result = await session.execute(statement)
        analysis = result.scalar_one_or_none()

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


@router.get("/json/preview/{analysis_id}")
async def preview_analysis_json(
    analysis_id,
    user=Depends(fastapi_users.current_user(active=True)),
    session: AsyncSession = Depends(get_async_session)
):
    """
    预览JSON内容（不下载）
    """
    try:
        log.info("用户 {} 请求预览JSON: {}".format(user.id, analysis_id))

        statement = select(Analysis).where(
            Analysis.analysis_id == analysis_id,
            Analysis.user_id == user.id
        )
        result = await session.execute(statement)
        analysis = result.scalar_one_or_none()

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


@router.get("/list")
async def list_exportable_analyses(
    user=Depends(fastapi_users.current_user(active=True)),
    session: AsyncSession = Depends(get_async_session),
    limit=50,
    offset=0,
    status=None
):
    """
    获取可导出的分析列表
    """
    try:
        log.info("用户 {} 请求分析列表, status={}".format(user.id, status))

        statement = select(Analysis).where(Analysis.user_id == user.id)

        if status:
            statement = statement.where(Analysis.status == status)
        else:
            statement = statement.where(Analysis.status.in_(['completed', 'failed']))

        statement = statement.order_by(desc(Analysis.created_at))
        statement = statement.offset(offset).limit(limit)

        result = await session.execute(statement)
        analyses = result.scalars().all()

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


@router.post("/json/batch")
async def export_batch_json(
    analysis_ids,
    user=Depends(fastapi_users.current_user(active=True)),
    session: AsyncSession = Depends(get_async_session)
):
    """
    批量导出多个分析结果的JSON文件（返回ZIP压缩包）
    """
    import zipfile

    try:
        log.info("用户 {} 请求批量导出: {} 个文件".format(user.id, len(analysis_ids)))

        statement = select(Analysis).where(
            Analysis.analysis_id.in_(analysis_ids),
            Analysis.user_id == user.id,
            Analysis.status == "completed"
        )
        result = await session.execute(statement)
        analyses = result.scalars().all()

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