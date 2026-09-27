# 分析记录数据模型

import uuid
from datetime import datetime
from typing import Optional
from pydantic import ConfigDict
from sqlmodel import Field, SQLModel
# 确保这里没有 'from app.models.analysis import Analysis' 这一行

class Analysis(SQLModel, table=True):
    # model_used 以 "model_" 开头，会撞上 pydantic 的受保护命名空间；这里显式放开。
    model_config = ConfigDict(protected_namespaces=())

    __tablename__ = "analyses" # 定义数据库表名

    # --- 核心字段 ---
    analysis_id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, index=True)
    status: str = Field(default="pending", index=True) # 任务状态: pending, processing, queued, completed, failed
    # 分析类型（对应 app/core/tasks.py 的注册表，如 stem=茎秆截面、leaf=剑叶）
    task_type: str = Field(default="stem", index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
    # 推理起止时间（均为 UTC）。用于主页的"近 7 天完成数 / 平均耗时"统计；
    # 老记录没有这两个字段，统计时按缺失跳过，不影响其它功能。
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)

    # --- 文件路径字段 ---
    original_file_path: Optional[str] = Field(default=None)
    annotated_image_path: Optional[str] = Field(default=None) # 推理后带掩膜的图片
    result_json_path: Optional[str] = Field(default=None) # LabelMe JSON 文件
    excel_report_path: Optional[str] = Field(default=None) # Excel 报告文件

    # --- 关联用户 (外键) ---
    # 这个字段将这条分析记录与 users 表中的一个用户关联起来
    user_id: uuid.UUID = Field(foreign_key="users.id")
    
    # --- 批量上传支持 ---
    batch_id: Optional[uuid.UUID] = Field(default=None, index=True) # 批次ID，用于批量上传
    batch_index: Optional[int] = Field(default=None) # 在批次中的序号

    # --- 模型选择 ---
    # 本次分析实际使用的分析类型/模型 key（对应 task_catalog 的 key，如 stem、leaf_our）
    model_used: Optional[str] = Field(default=None)

    # --- 失败原因 ---
    # 后台任务失败时的中文描述，供前端直接展示
    error_message: Optional[str] = Field(default=None)