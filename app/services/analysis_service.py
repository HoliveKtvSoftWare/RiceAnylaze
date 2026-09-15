# 分析服务

import os
import logging
from datetime import datetime
from typing import Optional

# 导入我们重构后的、健壮的服务模块
from app.services.yolo_inference import run_system

# 导入数据库相关的工具
from sqlmodel import create_engine, Session, select
from app.core.config import settings
from app.models.analysis import Analysis

# 设置日志
log = logging.getLogger(__name__)

# 创建一个同步的数据库引擎
sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
sync_engine = create_engine(sync_db_url, echo=False)

# 确认函数定义包含了 original_filename: str
def run_full_analysis(analysis_id: str, original_file_path: str, user_id: str, original_filename: str, model_name:
Optional[str] = None):
    """
    后台任务主函数，使用原始文件名进行输出。

    Args:
        analysis_id: 分析记录的 UUID
        original_file_path: 原图存储路径
        user_id: 用户 UUID
        original_filename: 原始文件名（含时间戳）
        model_name: 用户选择的模型名称（对应 .env 中 YOLO_MODELS 的 key）
    """
    try:
        log.info(f"--- [任务 {analysis_id}] 开始处理 (原始文件名: {original_filename}, 模型: {model_name}) ---")

        # 步骤 1: 根据 model_name 解析出实际模型路径
        model_path = settings.get_model_path(model_name)
        log.info(f"解析模型: model_name={model_name} -> model_path={model_path}")

        # 步骤 2: 准备本次任务专属的输出文件夹
        original_filename_without_ext = os.path.splitext(original_filename)[0]
        output_dir = os.path.join(settings.STORAGE_PATH, user_id, original_filename_without_ext)
        os.makedirs(output_dir, exist_ok=True)
        log.info(f"输出目录已创建: {output_dir}")

        # 步骤 3: 调用 YOLO 推理服务
        log.info(f"开始执行 YOLO 推理... 图片: {original_file_path}")
        annotated_image_path, json_output_path = run_system(
            model_path=model_path,
            image_path=original_file_path,
            output_path=output_dir,
            output_basename=original_filename_without_ext
        )
        log.info(f"YOLO 推理完成。JSON 已保存至: {json_output_path}")

        # 步骤 4: 更新数据库（含 model_used）
        log.info(f"开始更新数据库状态为 'completed'...")
        with Session(sync_engine) as session:
            statement = select(Analysis).where(Analysis.analysis_id == analysis_id)
            analysis_record = session.exec(statement).one()

            analysis_record.status = "completed"
            analysis_record.annotated_image_path = annotated_image_path
            analysis_record.result_json_path = json_output_path
            analysis_record.model_used = model_name if model_name else "default"
            analysis_record.updated_at = datetime.utcnow()

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
                    session.add(analysis_record)
                    session.commit()
            log.info(f"数据库状态已更新为 'failed'，error_message={_summarize_error(e, model_name)}")
        except Exception as db_error:
            log.error(f"在更新任务状态为 'failed' 时再次发生错误: {db_error}")

        # 重新抛出异常，让 FastAPI BackgroundTasks 知道出错了
        raise e


def _summarize_error(exc: Exception, model_name: Optional[str]) -> str:
    """
    将底层异常转化为前端能直接看懂的中文提示，用于 Analysis.error_message。
    """
    if isinstance(exc, FileNotFoundError) and "模型文件不存在" in str(exc):
        return f"未部署该模型: {model_name if model_name else 'default'}"
    msg = str(exc) if str(exc) else exc.__class__.__name__
    return msg[:500]