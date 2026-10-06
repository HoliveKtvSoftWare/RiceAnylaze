"""Upload, batch and deletion workflows with injected persistence."""
import uuid
import os
import logging
from datetime import datetime
from fastapi import HTTPException
from app.core.config import settings
from app.features.task_catalog import get_task, is_valid_task_type, resolve_task_type
from app.features.analysis import queue as analysis_queue
from app.infrastructure.database.repositories import BatchRepository
from app.infrastructure.storage.previews import ensure_preview
from app.infrastructure.storage.files import (
    files_of_analysis as _files_of_analysis,
    directories_of_analysis as _dirs_of_analysis,
    remove_files as _remove_files,
    remove_empty_dirs as _remove_empty_dirs,
    save_upload_file,
)
from app.models.analysis import Analysis
from app.models.batch import UploadBatch

log = logging.getLogger(__name__)

# 把前端自造的批次串（如 "batch_1738..._ab12"）稳定映射成 UUID 用的命名空间。
# 用 uuid5 而不是随机 UUID，才能让同一批次的多张图落到同一个 batch_id 上。
_CLIENT_BATCH_NAMESPACE = uuid.UUID("8f2b1c94-7d63-4e0a-9b21-5c3d7a6e4f10")


def _client_batch_uuid(batch_id, user_id):
    """前端 batch_id -> UUID。本身是 UUID 就直接用，否则按 (用户, 批次串) 派生。"""
    try:
        return uuid.UUID(str(batch_id))
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid5(_CLIENT_BATCH_NAMESPACE, f"{user_id}:{batch_id}")


def _resolve_task_type(task_type, model_name) -> str:
    """model_name（新版前端）优先于 task_type（旧客户端）；两者都接受 key 与中文显示名。"""
    requested = model_name or task_type
    if not is_valid_task_type(requested):
        log.warning(f"收到未知的分析类型/模型 '{requested}'，已回退为 stem")
    return resolve_task_type(requested)


async def _resolve_batch_id(batch_id, batch_name, user, repository, file_count):
    """取得本次上传应归属的批次 UUID。

    前端"选择多张单图"会给每张图发同一个 batch_id，这里复用它并累加文件数，
    这样历史记录才能把这批图折叠成一个批次；文件夹上传不传 batch_id，则新建。
    """
    if batch_id:
        client_uuid = _client_batch_uuid(batch_id, user.id)
        existing = await BatchRepository(repository.session).get(client_uuid, user.id)
        if existing is not None:
            existing.file_count = (existing.file_count or 0) + file_count
            if batch_name and not existing.name:
                existing.name = batch_name
            await repository.save(existing)
            log.info(f"复用已有批次: {existing.batch_id} (累计 {existing.file_count} 个文件)")
            return existing.batch_id, False
        new_batch = UploadBatch(batch_id=client_uuid, file_count=file_count,
                                user_id=user.id, name=batch_name)
        await repository.save(new_batch)
        log.info(f"按前端 batch_id 创建批次: {new_batch.batch_id}")
        return new_batch.batch_id, True

    batch_uuid = uuid.uuid4()
    new_batch = UploadBatch(batch_id=batch_uuid, file_count=file_count,
                            user_id=user.id, name=batch_name)
    await repository.save(new_batch)
    log.info(f"创建批次成功: {new_batch.batch_id}, 文件数量: {file_count}")
    return batch_uuid, True


def _store_original(file, user, analysis_id) -> str:
    """把上传流落盘到用户原图目录，返回保存路径（文件名以 analysis_id 开头）。"""
    originals_dir = os.path.join(settings.STORAGE_PATH, "originals", str(user.id))
    os.makedirs(originals_dir, exist_ok=True)

    clean_filename = os.path.basename(file.filename).replace('/', '_').replace('\\', '_')
    # 在文件名中添加上传时间（格式：YYYYMMDD_HHMMSS）
    upload_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = os.path.splitext(clean_filename)
    unique_filename_base = f"{analysis_id}_{name}_{upload_time}{ext}"
    saved_file_path = os.path.join(originals_dir, unique_filename_base)

    log.info(f"正在保存上传的文件至: {saved_file_path} (原始名: {file.filename})")
    try:
        save_upload_file(file.file, saved_file_path)
    except Exception as e:
        log.error(f"保存文件失败: {e}")
        raise HTTPException(status_code=500, detail="无法保存上传的文件。")

    # 生成浏览器可直接显示的预览图（.tif/.tiff 无法在 <img> 里渲染）
    ensure_preview(saved_file_path)
    return saved_file_path


def _enqueue(analysis, saved_file_path, unique_filename_base, user, task_type, model_name):
    """把一次分析排入串行队列，返回排号。"""
    try:
        return analysis_queue.enqueue_analysis(
            str(analysis.analysis_id),
            {
                "original_file_path": saved_file_path,
                "user_id": str(user.id),
                "original_filename": unique_filename_base,
                "task_type": task_type,
                "model_name": model_name,
            },
        )
    except Exception as e:
        log.error(f"分析任务入队失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="无法将任务加入分析队列。")


async def get_analysis_queue(user):
    """分析队列概况：正在执行的任务与排队中的任务。

    后端是**单 worker 串行**执行（一次只跑一张图），因此 `pendingCount`
    就是"前面还有几张在等"。前端据此区分"排队中"和"正在处理"。
    """
    return analysis_queue.queue_snapshot()


async def upload_image(file, task_type, user, repository, model_name=None,
                       batch_id=None, batch_name=None):
    """
    接收用户上传：保存文件，创建记录，排入分析队列（串行执行）。
    单文件上传时自动创建批次。

    分析类型二选一（同时传时 model_name 优先）：
      model_name: 新版前端从 /analysis/models 拿到并回传的模型名（key 或中文显示名）
      task_type:  分析类型 key（stem=茎秆截面，默认 / leaf=剑叶），未知值回退为 stem
    """
    task_type = _resolve_task_type(task_type, model_name)
    task = get_task(task_type)
    log.info(f"用户 {user.id} 上传单文件，分析类型/模型: {task.name} ({task_type})")

    batch_uuid, _ = await _resolve_batch_id(batch_id, batch_name, user, repository, file_count=1)

    analysis_uuid = uuid.uuid4()
    saved_file_path = _store_original(file, user, analysis_uuid)
    unique_filename_base = os.path.basename(saved_file_path)

    log.info(f"正在为用户 {user.id} 创建分析记录...")
    new_analysis = Analysis(
        analysis_id=analysis_uuid,
        user_id=user.id,
        status="queued",
        task_type=task_type,
        model_used=model_name if model_name else "default",
        original_file_path=saved_file_path,
        batch_id=batch_uuid,
        batch_index=0
    )
    await repository.save(new_analysis)
    log.info(f"分析记录创建成功: {new_analysis.analysis_id} (类型: {task_type})")

    # 排入串行队列（单 worker，一次只跑一张图），不再用 BackgroundTasks 并发派发
    position = _enqueue(new_analysis, saved_file_path, unique_filename_base,
                        user, task_type, model_name)

    log.info(f"任务 {new_analysis.analysis_id} 已入队（排号 {position}）。")
    return {
        "message": "文件已加入分析队列，将按顺序处理。",
        "analysis_id": new_analysis.analysis_id,
        "task_type": task_type,
        "model_used": model_name if model_name else "default",
        "batch_id": batch_uuid,
        "queue_position": position,
        "original_filename": file.filename
    }


async def upload_images_batch(files, task_type, user, repository, model_name=None,
                              batch_id=None, batch_name=None):
    """
    批量上传图片：创建批次，保存文件，创建记录，**按顺序**排入分析队列。

    与逐个上传的区别：一次请求建一个批次、写 1 次批次记录，
    并且这 N 张图会连续排在队列里依次执行（单 worker，不会并发跑）。

    分析类型二选一（同时传时 model_name 优先）：model_name / task_type；
    整批使用同一类型。
    """
    if not files:
        raise HTTPException(status_code=400, detail="未上传任何文件")

    task_type = _resolve_task_type(task_type, model_name)
    task = get_task(task_type)
    log.info(f"用户 {user.id} 批量上传 {len(files)} 个文件，分析类型/模型: {task.name} ({task_type})")

    batch_uuid, _ = await _resolve_batch_id(batch_id, batch_name, user, repository,
                                            file_count=len(files))

    submitted_analyses = []

    for index, file in enumerate(files):
        analysis_uuid = uuid.uuid4()
        saved_file_path = _store_original(file, user, analysis_uuid)
        unique_filename_base = os.path.basename(saved_file_path)

        log.info(f"正在为用户 {user.id} 创建分析记录 ({index + 1}/{len(files)})...")
        new_analysis = Analysis(
            analysis_id=analysis_uuid,
            user_id=user.id,
            status="queued",
            task_type=task_type,
            model_used=model_name if model_name else "default",
            original_file_path=saved_file_path,
            batch_id=batch_uuid,
            batch_index=index
        )
        await repository.save(new_analysis)

        # 依次排入串行队列：这一批会连续执行，但**同一时刻只跑一张**
        position = _enqueue(new_analysis, saved_file_path, unique_filename_base,
                            user, task_type, model_name)

        submitted_analyses.append({
            "analysis_id": new_analysis.analysis_id,
            "original_filename": file.filename,
            "queue_position": position,
        })

    log.info(f"批次 {batch_uuid} 中 {len(files)} 个任务已依次入队（串行执行）。")
    return {
        "message": f"{len(files)} 个文件已成功提交后台处理。",
        "task_type": task_type,
        "model_used": model_name if model_name else "default",
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

        # 删除相关文件（含自动生成的原图预览），并清掉留空的样本输出目录
        _remove_files(_files_of_analysis(analysis))
        _remove_empty_dirs(_dirs_of_analysis(analysis))

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
                # 与单条删除口径一致：原图、预览、结果图、结果 JSON 全清，
                # 留空的样本输出目录也一并收掉
                _remove_files(_files_of_analysis(analysis))
                _remove_empty_dirs(_dirs_of_analysis(analysis))

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
