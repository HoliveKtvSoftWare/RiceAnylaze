# 分析服务

import os
import logging
from datetime import datetime
from typing import Optional

# 导入我们重构后的、健壮的服务模块
from app.infrastructure.inference.runner import run_system

# 导入数据库相关的工具
from sqlmodel import Session, select
from app.core.config import settings
from app.features.task_catalog.catalog import get_task
from app.infrastructure.database.session import sync_engine
from app.infrastructure.inference.sidecar import run_via_sidecar
from app.models.analysis import Analysis

# 设置日志
log = logging.getLogger(__name__)


def _run_via_sidecar(task, image_path: str, output_dir: str, basename: str):
    """Supply the application's .env settings to the independent adapter."""
    return run_via_sidecar(
        task, image_path, output_dir, basename,
        fork_python=settings.FORK_PYTHON,
        script=settings.SIDECAR_SCRIPT,
        fork_pylibs=settings.FORK_PYLIBS,
        fork_project=settings.FORK_PROJECT,
    )


def _mark_started(analysis_id: str) -> None:
    """把记录标记为 processing 并写下开始时间；失败只记日志，不影响推理。

    状态语义：上传后是 `queued`（在单 worker 串行队列里排队），worker 真正取到
    这一条、开始跑的时候才转成 `processing`。前端据此区分"排队中 / 处理中"，
    并且两种状态都属于"还没结束"，都会继续轮询。
    """
    try:
        with Session(sync_engine) as session:
            statement = select(Analysis).where(Analysis.analysis_id == analysis_id)
            record = session.exec(statement).one_or_none()
            if record:
                record.status = "processing"
                record.started_at = datetime.utcnow()
                session.add(record)
                session.commit()
    except Exception as e:                                            # noqa: BLE001
        log.warning(f"记录 processing 状态 / started_at 失败（不影响推理）: {e}")


def run_full_analysis(analysis_id: str, original_file_path: str, user_id: str, original_filename: str,
                      task_type: str = "stem", model_name: Optional[str] = None):
    """
    后台任务主函数，使用原始文件名进行输出。

    task_type 决定使用哪个模型以及用哪套后处理口径（见 app/core/tasks.py 注册表）。

    Args:
        analysis_id: 分析记录 ID
        original_file_path: 已保存的原图路径
        user_id: 所属用户 ID
        original_filename: 输出用的基础文件名
        task_type: 分析类型，'stem'（茎秆截面，默认）或 'leaf'（剑叶）
        model_name: 用户在前端选择的模型名，用于留档与失败提示（实际口径由 task_type 决定）
    """
    task = get_task(task_type)
    try:
        log.info(f"--- [任务 {analysis_id}] 开始处理 (类型: {task.name} / {task.key}, 原始文件名: {original_filename}) ---")

        # 记录开始处理（status -> processing）与开始时间（主页的"平均耗时"用它和
        # finished_at 相减）。放在最前面：包含输出目录创建等准备工作，
        # 用户感知的等待时长就是这个区间。
        _mark_started(analysis_id)

        # 【检查点 2】确认这里使用 original_filename 创建 output_dir
        # 步骤 1: 准备本次任务专属的输出文件夹
        original_filename_without_ext = os.path.splitext(original_filename)[0]
        output_dir = os.path.join(settings.STORAGE_PATH, user_id, original_filename_without_ext)
        os.makedirs(output_dir, exist_ok=True)
        log.info(f"输出目录已创建: {output_dir}")

        # 步骤 2: 执行推理。runtime="fork" 的对比方法权重依赖另一套 ultralytics，
        # 交给旁路子进程执行；其余任务在当前进程内直接推理。
        log.info(f"开始执行推理... 模型: {task.model_path} 图片: {original_file_path} (runtime={task.runtime})")
        if task.runtime == 'fork':
            annotated_image_path, json_output_path = _run_via_sidecar(
                task, original_file_path, output_dir, original_filename_without_ext)
        else:
            annotated_image_path, json_output_path = run_system(
                model_path=task.model_path,
                image_path=original_file_path,
                output_path=output_dir,
                output_basename=original_filename_without_ext,  # <-- 传递基础文件名
                smooth=task.smooth,
                smooth_exclude=task.smooth_exclude,
                embed_image=task.embed_image,
                colors=task.colors,
                draw_first=task.draw_first,
                outline_labels=task.outline_labels,
                imgsz=task.predict_imgsz,
                conf=task.conf,
                iou=task.iou,
                retina_masks=task.retina_masks,
                preview_smooth=task.preview_smooth,
                preserve_mask_topology=task.preserve_mask_topology,
                validate_side_bundles=task.validate_side_bundles,
            )
        log.info(f"YOLO 推理完成。JSON 已保存至: {json_output_path}")

        # 步骤 4: 更新数据库
        log.info(f"开始更新数据库状态为 'completed'...")
        finished_at = datetime.utcnow()
        with Session(sync_engine) as session:
            statement = select(Analysis).where(Analysis.analysis_id == analysis_id)
            analysis_record = session.exec(statement).one()

            analysis_record.status = "completed"
            # 以实际使用的模型类型为准，避免提交时的类型与真实执行不一致
            analysis_record.task_type = task.key
            analysis_record.model_used = model_name if model_name else "default"
            analysis_record.error_message = None
            analysis_record.annotated_image_path = annotated_image_path
            analysis_record.result_json_path = json_output_path
            analysis_record.updated_at = finished_at
            analysis_record.finished_at = finished_at

            session.add(analysis_record)
            session.commit()

        log.info(f"--- [任务 {analysis_id}] 已成功处理 ---")

    except Exception as e:
        log.error(f"--- [任务 {analysis_id}] 发生严重错误: {e} ---", exc_info=True)
        try:
            with Session(sync_engine) as session:
                statement = select(Analysis).where(Analysis.analysis_id == analysis_id)
                analysis_record = session.exec(statement).one_or_none()
                if analysis_record:
                    analysis_record.status = "failed"
                    analysis_record.error_message = _summarize_error(e, model_name)
                    analysis_record.updated_at = datetime.utcnow()
                    # 失败也算一次完整执行，记录结束时间以便统计耗时
                    analysis_record.finished_at = datetime.utcnow()
                    session.add(analysis_record)
                    session.commit()
            log.info(f"数据库状态已更新为 'failed'。")
        except Exception as db_error:
            log.error(f"在更新任务状态为 'failed' 时再次发生错误: {db_error}")

        # 重新抛出异常，让 FastAPI BackgroundTasks 知道出错了
        raise e


def _summarize_error(exc: Exception, model_name: Optional[str]) -> str:
    """把底层异常转成前端能直接看懂的中文提示，写入 Analysis.error_message。"""
    if isinstance(exc, FileNotFoundError) and "模型文件不存在" in str(exc):
        return f"未部署该模型: {model_name if model_name else 'default'}"
    message = str(exc) if str(exc) else exc.__class__.__name__
    return message[:500]
