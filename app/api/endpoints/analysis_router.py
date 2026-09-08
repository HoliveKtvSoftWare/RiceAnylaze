from datetime import datetime
import uuid
import os
import shutil
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
from app.models.batch import UploadBatch
# 设置日志
log = logging.getLogger(__name__)

router = APIRouter()
current_active_user = fastapi_users.current_user(active=True)

@router.get("/history")
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
            "batchId": str(record.batch_id) if record.batch_id else None,
            "batchIndex": record.batch_index,
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
    单文件上传时自动创建批次。
    """
    # 创建批次（单文件上传也创建批次，保持一致性）
    batch_uuid = uuid.uuid4()
    new_batch = UploadBatch(
        batch_id=batch_uuid,
        file_count=1,
        user_id=user.id
    )
    db.add(new_batch)
    await db.commit()
    await db.refresh(new_batch)
    log.info(f"创建批次成功: {new_batch.batch_id}")

    originals_dir = os.path.join(settings.STORAGE_PATH, "originals", str(user.id))
    os.makedirs(originals_dir, exist_ok=True)

    analysis_uuid = uuid.uuid4()
    clean_filename = os.path.basename(file.filename).replace('/', '_').replace('\\', '_')
    # 在文件名中添加上传时间（格式：YYYYMMDD_HHMMSS）
    upload_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = os.path.splitext(clean_filename)
    unique_filename_base = f"{analysis_uuid}_{name}_{upload_time}{ext}"
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
        original_file_path=saved_file_path,
        batch_id=batch_uuid,
        batch_index=0
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
            original_filename=unique_filename_base
        )
        log.debug(f"后台任务 run_full_analysis 添加成功 for analysis_id={new_analysis.analysis_id}")
    except Exception as e:
         log.error(f"添加后台任务时发生错误: {e}", exc_info=True)
         raise HTTPException(status_code=500, detail="无法启动后台分析任务。")

    log.info(f"任务 {new_analysis.analysis_id} 已成功提交到后台。")
    return {
        "message": "文件已成功提交后台处理。",
        "analysis_id": new_analysis.analysis_id,
        "batch_id": batch_uuid,
        "original_filename": file.filename
    }

@router.post("/upload/batch")
async def upload_images_batch(
    tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    user: UserTable = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_session)
):
    """
    批量上传图片：创建批次，保存文件，创建记录，提交后台任务。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未上传任何文件")

    # 创建批次
    batch_uuid = uuid.uuid4()
    new_batch = UploadBatch(
        batch_id=batch_uuid,
        file_count=len(files),
        user_id=user.id
    )
    db.add(new_batch)
    await db.commit()
    await db.refresh(new_batch)
    log.info(f"创建批次成功: {new_batch.batch_id}, 文件数量: {len(files)}")

    originals_dir = os.path.join(settings.STORAGE_PATH, "originals", str(user.id))
    os.makedirs(originals_dir, exist_ok=True)

    submitted_analyses = []

    for index, file in enumerate(files):
        analysis_uuid = uuid.uuid4()
        clean_filename = os.path.basename(file.filename).replace('/', '_').replace('\\', '_')
        # 在文件名中添加上传时间（格式：YYYYMMDD_HHMMSS）
        upload_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(clean_filename)
        unique_filename_base = f"{analysis_uuid}_{name}_{upload_time}{ext}"
        saved_file_path = os.path.join(originals_dir, unique_filename_base)

        log.info(f"正在保存上传的文件 {index+1}/{len(files)} 至: {saved_file_path} (原始名: {file.filename})")
        try:
            with open(saved_file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        except Exception as e:
            log.error(f"保存文件 {file.filename} 失败: {e}")
            raise HTTPException(status_code=500, detail=f"无法保存文件 {file.filename}。")

        log.info(f"正在为用户 {user.id} 创建分析记录...")
        new_analysis = Analysis(
            analysis_id=analysis_uuid,
            user_id=user.id,
            status="processing",
            original_file_path=saved_file_path,
            batch_id=batch_uuid,
            batch_index=index
        )
        db.add(new_analysis)
        await db.commit()
        await db.refresh(new_analysis)
        log.info(f"分析记录创建成功: {new_analysis.analysis_id}")

        # 添加后台任务
        try:
            tasks.add_task(
                run_full_analysis,
                analysis_id=str(new_analysis.analysis_id),
                original_file_path=saved_file_path,
                user_id=str(user.id),
                original_filename=unique_filename_base
            )
        except Exception as e:
            log.error(f"添加后台任务时发生错误: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="无法启动后台分析任务。")

        submitted_analyses.append({
            "analysis_id": new_analysis.analysis_id,
            "original_filename": file.filename
        })

    log.info(f"批次 {batch_uuid} 中 {len(files)} 个任务已成功提交到后台。")
    return {
        "message": f"{len(files)} 个文件已成功提交后台处理。",
        "batch_id": batch_uuid,
        "total_files": len(files),
        "analyses": submitted_analyses
    }

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
    try:
        analysis_ids = request_data.get("analysisIds", [])
        if not analysis_ids:
            raise HTTPException(status_code=400, detail="请传入 analysisIds 列表")

        log.info(f"用户 {user.id} 请求批量删除 {len(analysis_ids)} 条分析记录")

        statement = select(Analysis).where(
            Analysis.analysis_id.in_(analysis_ids),
            Analysis.user_id == user.id
        )
        result = await db.execute(statement)
        analyses = result.scalars().all()

        if not analyses:
            raise HTTPException(status_code=404, detail="没有找到可删除的分析记录")

        deleted_count = 0
        skipped_ids = []

        for analysis in analyses:
            try:
                files_to_delete = [
                    analysis.original_file_path,
                    analysis.annotated_image_path,
                    analysis.result_json_path
                ]
                for file_path in files_to_delete:
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            log.error(f"删除文件 {file_path} 时出错: {e}")

                await db.delete(analysis)
                deleted_count += 1
            except Exception as e:
                log.error(f"删除分析记录 {analysis.analysis_id} 时出错: {e}")
                skipped_ids.append(str(analysis.analysis_id))

        await db.commit()
        log.info(f"批量删除完成: 成功 {deleted_count} 条, 跳过 {len(skipped_ids)} 条")

        return {
            "message": f"成功删除 {deleted_count} 条记录",
            "deleted_count": deleted_count,
            "total_requested": len(analysis_ids),
            "skipped_ids": skipped_ids
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"批量删除时发生错误: {e}")
        raise HTTPException(status_code=500, detail=f"批量删除失败: {str(e)}")