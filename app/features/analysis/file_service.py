"""Upload, batch and deletion workflows with injected persistence."""
import uuid
import os
import logging
from datetime import datetime
from fastapi import HTTPException
from app.core.config import settings
from app.features.task_catalog.catalog import get_task, is_valid_task_type, normalize_task_type
from app.features.analysis import queue as analysis_queue
from app.infrastructure.storage.previews import ensure_preview
from app.infrastructure.storage.files import files_of_analysis as _files_of_analysis, remove_files as _remove_files, save_upload_file
from app.models.analysis import Analysis
from app.models.batch import UploadBatch

log = logging.getLogger(__name__)


async def get_analysis_queue(user):
    """分析队列概况：正在执行的任务与排队中的任务。

    后端是**单 worker 串行**执行（一次只跑一张图），因此 `pendingCount`
    就是"前面还有几张在等"。前端据此区分"排队中"和"正在处理"。
    """
    return analysis_queue.queue_snapshot()


async def upload_image(file, task_type, user, repository):
    """
    接收用户上传：保存文件，创建记录，排入分析队列（串行执行）。
    单文件上传时自动创建批次。

    task_type: 分析类型（stem=茎秆截面，默认 / leaf=剑叶），未知值回退为 stem。
    """
    if not is_valid_task_type(task_type):
        log.warning(f"收到未知的分析类型 '{task_type}'，已回退为 stem")
    task_type = normalize_task_type(task_type)
    task = get_task(task_type)
    log.info(f"用户 {user.id} 上传单文件，分析类型: {task.name} ({task_type})")

    # 创建批次（单文件上传也创建批次，保持一致性）
    batch_uuid = uuid.uuid4()
    new_batch = UploadBatch(
        batch_id=batch_uuid,
        file_count=1,
        user_id=user.id
    )
    await repository.save(new_batch)
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
        save_upload_file(file.file, saved_file_path)
    except Exception as e:
        log.error(f"保存文件失败: {e}")
        raise HTTPException(status_code=500, detail="无法保存上传的文件。")

    # 生成浏览器可直接显示的预览图（.tif/.tiff 无法在 <img> 里渲染）
    ensure_preview(saved_file_path)

    log.info(f"正在为用户 {user.id} 创建分析记录...")
    new_analysis = Analysis(
        analysis_id=analysis_uuid,
        user_id=user.id,
        status="queued",
        task_type=task_type,
        original_file_path=saved_file_path,
        batch_id=batch_uuid,
        batch_index=0
    )
    await repository.save(new_analysis)
    log.info(f"分析记录创建成功: {new_analysis.analysis_id} (类型: {task_type})")

    # 排入串行队列（单 worker，一次只跑一张图），不再用 BackgroundTasks 并发派发
    try:
        position = analysis_queue.enqueue_analysis(
            str(new_analysis.analysis_id),
            {
                "original_file_path": saved_file_path,
                "user_id": str(user.id),
                "original_filename": unique_filename_base,
                "task_type": task_type,
            },
        )
    except Exception as e:
        log.error(f"分析任务入队失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="无法将任务加入分析队列。")

    log.info(f"任务 {new_analysis.analysis_id} 已入队（排号 {position}）。")
    return {
        "message": "文件已加入分析队列，将按顺序处理。",
        "analysis_id": new_analysis.analysis_id,
        "task_type": task_type,
        "batch_id": batch_uuid,
        "queue_position": position,
        "original_filename": file.filename
    }


async def upload_images_batch(files, task_type, user, repository):
    """
    批量上传图片：创建批次，保存文件，创建记录，**按顺序**排入分析队列。

    与逐个上传的区别：一次请求建一个批次、写 1 次批次记录，
    并且这 N 张图会连续排在队列里依次执行（单 worker，不会并发跑）。

    task_type: 分析类型（stem=茎秆截面，默认 / leaf=剑叶）；整批使用同一类型。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未上传任何文件")

    if not is_valid_task_type(task_type):
        log.warning(f"收到未知的分析类型 '{task_type}'，已回退为 stem")
    task_type = normalize_task_type(task_type)
    task = get_task(task_type)
    log.info(f"用户 {user.id} 批量上传 {len(files)} 个文件，分析类型: {task.name} ({task_type})")

    # 创建批次
    batch_uuid = uuid.uuid4()
    new_batch = UploadBatch(
        batch_id=batch_uuid,
        file_count=len(files),
        user_id=user.id
    )
    await repository.save(new_batch)
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
            save_upload_file(file.file, saved_file_path)
        except Exception as e:
            log.error(f"保存文件 {file.filename} 失败: {e}")
            raise HTTPException(status_code=500, detail=f"无法保存文件 {file.filename}。")

        # 生成浏览器可直接显示的预览图
        ensure_preview(saved_file_path)

        log.info(f"正在为用户 {user.id} 创建分析记录...")
        new_analysis = Analysis(
            analysis_id=analysis_uuid,
            user_id=user.id,
            status="queued",
            task_type=task_type,
            original_file_path=saved_file_path,
            batch_id=batch_uuid,
            batch_index=index
        )
        await repository.save(new_analysis)
        log.info(f"分析记录创建成功: {new_analysis.analysis_id} (类型: {task_type})")

        # 依次排入串行队列：这一批会连续执行，但**同一时刻只跑一张**
        try:
            position = analysis_queue.enqueue_analysis(
                str(new_analysis.analysis_id),
                {
                    "original_file_path": saved_file_path,
                    "user_id": str(user.id),
                    "original_filename": unique_filename_base,
                    "task_type": task_type,
                },
            )
        except Exception as e:
            log.error(f"分析任务入队失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="无法将任务加入分析队列。")

        submitted_analyses.append({
            "analysis_id": new_analysis.analysis_id,
            "original_filename": file.filename,
            "queue_position": position,
        })

    log.info(f"批次 {batch_uuid} 中 {len(files)} 个任务已依次入队（串行执行）。")
    return {
        "message": f"{len(files)} 个文件已成功提交后台处理。",
        "task_type": task_type,
        "batch_id": batch_uuid,
        "total_files": len(files),
        "analyses": submitted_analyses
    }


async def delete_analysis(analysis_id, user, repository):
    """
    删除指定的分析记录
    """
    try:
        log.info(f"用户 {user.id} 请求删除分析记录: {analysis_id}")

        # 查找分析记录
        analysis = await repository.get(analysis_id, user.id)

        if not analysis:
            log.warning(f"分析记录 {analysis_id} 不存在或不属于用户 {user.id}")
            raise HTTPException(status_code=404, detail="分析记录不存在或无权操作")

        # 删除相关文件（含自动生成的原图预览）
        _remove_files(_files_of_analysis(analysis))

        # 删除数据库记录
        await repository.delete(analysis)
        await repository.commit()
        log.info(f"分析记录 {analysis_id} 已成功删除")

        return {"message": "分析记录已成功删除"}

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"删除分析记录时发生错误: {e}")
        raise HTTPException(status_code=500, detail="删除分析记录时发生错误")


async def delete_analyses_batch(request_data, user, repository):
    """
    批量删除分析记录
    请求体: { "analysisIds": ["id1", "id2", "id3"] }
    """
    try:
        analysis_ids = request_data.get("analysisIds", [])
        if not analysis_ids:
            raise HTTPException(status_code=400, detail="请传入 analysisIds 列表")

        log.info(f"用户 {user.id} 请求批量删除 {len(analysis_ids)} 条分析记录")

        analyses = await repository.list(user.id, analysis_ids=analysis_ids, ordered=False)

        if not analyses:
            raise HTTPException(status_code=404, detail="没有找到可删除的分析记录")

        deleted_count = 0
        skipped_ids = []

        for analysis in analyses:
            try:
                # 与单条删除口径一致：原图、预览、结果图、结果 JSON 全清
                _remove_files(_files_of_analysis(analysis))

                await repository.delete(analysis)
                deleted_count += 1
            except Exception as e:
                log.error(f"删除分析记录 {analysis.analysis_id} 时出错: {e}")
                skipped_ids.append(str(analysis.analysis_id))

        await repository.commit()
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
