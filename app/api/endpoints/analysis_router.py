import uuid
import os
import shutil
from datetime import datetime
from fastapi import APIRouter, Depends, UploadFile, File, BackgroundTasks, HTTPException, Body
import logging
from typing import List, Dict, Any, Optional
from sqlmodel import select
from fastapi import Request
from sqlmodel.ext.asyncio.session import AsyncSession
from app.auth.core import fastapi_users
from app.models.user import UserTable
from app.core.config import settings
from app.services.analysis_service import run_full_analysis
from app.auth.db import get_async_session
from app.models.analysis import Analysis
from app.services.excel_download import excel_service
import base64
from pydantic import BaseModel

class ExportRequest(BaseModel):
    selectedColumns: List[str]

class BatchUploadRequest(BaseModel):
    folder_name: str
    file_count: int

# 设置日志
log = logging.getLogger(__name__)

router = APIRouter()
current_active_user = fastapi_users.current_user(active=True)

@router.get("/history")1
async def get_analysis_history(
    request: Request,
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
) -> List[Dict[str, Any]]:
    """
    获取当前登录用户的分析历史记录，包含可访问的文件 URL。
    """
    log.info(f"用户 {user.id} 请求分析历史记录...")
    statement = select(Analysis).where(Analysis.user_id == user.id).order_by(Analysis.created_at.desc())

    result = await db.execute(statement)
    history_records = result.scalars().all()

    log.info(f"为用户 {user.id} 找到 {len(history_records)} 条历史记录。")

    base_url = str(request.base_url)
    static_url_prefix = f"{base_url}static/"
    storage_base_path = settings.STORAGE_PATH.strip('.').strip('/').strip('\\') + '/'

    history_with_urls = []
    for record in history_records:
        def path_to_url(path: Optional[str]) -> Optional[str]:
            if not path:
                return None
            try:
                cleaned_path = path.replace('.\\', '').replace('./', '').replace('\\', '/')
                if cleaned_path.startswith(storage_base_path):
                    relative_path = cleaned_path[len(storage_base_path):]
                else:
                    log.warning(f"文件路径 '{cleaned_path}' 不包含预期的基础路径 '{storage_base_path}'，将尝试直接使用。")
                    relative_path = cleaned_path

                if relative_path.startswith('/'):
                     relative_path = relative_path[1:]

                final_url = f"{static_url_prefix}{relative_path}"
                log.debug(f"路径 '{path}' 转换为 URL: '{final_url}'")
                return final_url
            except Exception as e:
                 log.error(f"转换路径 '{path}' 为 URL 时出错: {e}")
                 return None

        original_filename = "未知文件名"
        if record.original_file_path:
             basename = os.path.basename(record.original_file_path)
             parts = basename.split('_', 1)
             if len(parts) == 2 and len(parts[0]) == 36:
                 original_filename = parts[1]
             else:
                 original_filename = basename

        history_with_urls.append({
            "analysisId": record.analysis_id,
            "createdAt": record.created_at,
            "status": record.status,
            "originalFilename": original_filename,
            "originalImageUrl": path_to_url(record.original_file_path),
            "annotatedImageUrl": path_to_url(record.annotated_image_path),
            "resultJsonUrl": path_to_url(record.result_json_path),
        })

    return history_with_urls

@router.post("/upload")
async def upload_image(
    tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    接收用户上传：保存文件，创建记录，提交后台任务。
    """
    originals_dir = os.path.join(settings.STORAGE_PATH, "originals", str(user.id))
    os.makedirs(originals_dir, exist_ok=True)

    analysis_uuid = uuid.uuid4()
    unique_filename_base = f"{analysis_uuid}_{file.filename}"
    saved_file_path = os.path.join(originals_dir, unique_filename_base)

    log.info(f"正在保存上传的文件至: {saved_file_path} (原始名: {file.filename})")
    try:
        with open(saved_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(f"保存文件失败: {e}")
        raise HTTPException(status_code=500, detail="无法保存上传的文件。")

    log.info(f"正在为用户 {user.id} 创建分析记录...")
    new_analysis = Analysis(
        analysis_id=analysis_uuid,
        user_id=user.id,
        status="processing",
        original_file_path=saved_file_path
    )
    db.add(new_analysis)
    await db.commit()
    await db.refresh(new_analysis)
    log.info(f"分析记录创建成功: {new_analysis.analysis_id}")

    log.debug(f"即将添加后台任务: run_full_analysis for analysis_id={new_analysis.analysis_id}")
    try:
        tasks.add_task(
            run_full_analysis,
            analysis_id=str(new_analysis.analysis_id),
            original_file_path=saved_file_path,
            user_id=str(user.id),
            original_filename=file.filename
        )
        log.debug(f"后台任务 run_full_analysis 添加成功 for analysis_id={new_analysis.analysis_id}")
    except Exception as e:
         log.error(f"添加后台任务时发生错误: {e}", exc_info=True)
         raise HTTPException(status_code=500, detail="无法启动后台分析任务。")

    log.info(f"任务 {new_analysis.analysis_id} 已成功提交到后台。")
    return {
        "message": "文件已成功提交后台处理。",
        "analysis_id": new_analysis.analysis_id,
        "original_filename": file.filename
    }

@router.get("/excel/columns")
async def get_export_columns():
    return {
        "available_columns": excel_service.get_available_columns(),
        "message": "可导出的列配置"
    }

@router.post("/excel/summary")
async def export_all_analysis_to_excel(
    request_data: ExportRequest = Body(...),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    导出当前用户的所有分析记录到一个Excel文件
    """
    try:
        selected_columns = request_data.selectedColumns
        log.info(f"用户 {user.id} 请求导出所有分析记录，选择的列: {selected_columns}")

        # 获取用户的所有分析记录
        statement = select(Analysis).where(
            Analysis.user_id == user.id,
            Analysis.status == "completed"
        ).order_by(Analysis.created_at.desc())
        
        result = await db.execute(statement)
        all_analyses = result.scalars().all()
        
        if not all_analyses:
            raise HTTPException(status_code=404, detail="没有找到已完成的分析记录")
        
        log.info(f"找到 {len(all_analyses)} 个已完成的分析记录")

        # 加载所有分析数据
        valid_analysis_data = []
        for analysis in all_analyses:
            try:
                analysis_data = excel_service.load_analysis_data(str(analysis.analysis_id), str(user.id))
                valid_analysis_data.append(analysis_data)
                log.debug(f"成功加载分析数据: {analysis.analysis_id}")
            except Exception as e:
                log.warning(f"加载分析数据失败 {analysis.analysis_id}: {e}")
                continue
        
        if not valid_analysis_data:
            raise HTTPException(status_code=404, detail="没有成功加载任何分析数据")
        
        log.info(f"成功加载 {len(valid_analysis_data)} 个分析任务的数据")

        # 使用批量导出方法
        excel_file = excel_service.export_all_to_excel(valid_analysis_data, selected_columns)
        
        log.info(f"所有分析记录Excel文件生成成功，包含 {len(valid_analysis_data)} 个样本")

        # 返回文件下载响应
        return {
            "filename": f"{len(valid_analysis_data)}条记录{datetime.now().strftime('%Y.%m.%d_%H：%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "total_samples": len(valid_analysis_data),
            "message": f"成功导出 {len(valid_analysis_data)} 个分析记录"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出所有分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"导出所有分析记录失败: {str(e)}")

@router.post("/excel/{analysis_id}")
async def export_analysis_to_excel(
    analysis_id: str,
    request_data: ExportRequest = Body(...),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    导出单个分析记录到Excel文件
    """
    try:
        selected_columns = request_data.selectedColumns
        log.info(f"用户 {user.id} 请求导出分析结果 {analysis_id}，选择的列: {selected_columns}")

        # 查找分析记录
        statement = select(Analysis).where(
            Analysis.analysis_id == analysis_id,
            Analysis.user_id == user.id
        )
        
        result = await db.execute(statement)
        analysis = result.scalar_one_or_none()
        
        if not analysis:
            log.warning(f"分析记录 {analysis_id} 不存在或不属于用户 {user.id}")
            raise HTTPException(status_code=404, detail="分析记录不存在")
        
        if analysis.status != "completed":
            log.warning(f"分析记录 {analysis_id} 状态为 {analysis.status}，无法导出")
            raise HTTPException(status_code=400, detail="分析记录尚未完成，无法导出")
        
        # 加载分析数据
        analysis_data = excel_service.load_analysis_data(str(analysis.analysis_id), str(user.id))

        # 生成Excel数据
        df = excel_service.generate_excel_data(analysis_data, selected_columns)

        # 创建Excel文件
        excel_file = excel_service.create_excel_file(df)
        
        log.info(f"分析记录 {analysis_id} Excel文件生成成功")

        # 返回文件下载响应
        return {
            "filename": f"{analysis_id}_{datetime.now().strftime('%Y.%m.%d_%H：%M')}.xlsx",
            "content": base64.b64encode(excel_file.getvalue()).decode('utf-8'),
            "message": "分析记录导出成功"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"导出分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"导出分析记录失败: {str(e)}")

@router.delete("/delete/{analysis_id}")
async def delete_analysis(
    analysis_id: str,
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    删除指定的分析记录
    """
    try:
        log.info(f"用户 {user.id} 请求删除分析记录: {analysis_id}")

        # 查找分析记录
        statement = select(Analysis).where(
            Analysis.analysis_id == analysis_id,
            Analysis.user_id == user.id
        )
        result = await db.execute(statement)
        analysis = result.scalars().first()

        if not analysis:
            log.warning(f"分析记录 {analysis_id} 不存在或不属于用户 {user.id}")
            raise HTTPException(status_code=404, detail="分析记录不存在或无权操作")

        # 删除相关文件
        files_to_delete = [
            analysis.original_file_path,
            analysis.annotated_image_path,
            analysis.result_json_path
        ]

        for file_path in files_to_delete:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    log.info(f"已删除文件: {file_path}")
                except Exception as e:
                    log.error(f"删除文件 {file_path} 时出错: {e}")

        # 删除数据库记录
        await db.delete(analysis)
        await db.commit()
        log.info(f"分析记录 {analysis_id} 已成功删除")

        return {"message": "分析记录已成功删除"}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"删除分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail="删除分析记录时发生错误")