# 用户数据模型

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

# ---------------------------------------------------------------------------
# 重要：fastapi-users v13+ 需要我们定义与数据库表完全对应的模型
# 这个模型将包含所有我们需要的新字段
# ---------------------------------------------------------------------------
class UserTable(SQLModel, table=True):
    __tablename__ = "users"  # 定义数据库中的表名

    # --- 核心认证字段 (与 fastapi-users 兼容) ---
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True, max_length=255)
    hashed_password: str = Field(max_length=1023)
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)

    # --- 我们新增的业务与扩展字段 ---

    # 角色与权限
    role: int = Field(default=2, description="1: Admin, 2: Regular User")

    # 手机与单位信息
    phone_number: Optional[str] = Field(default=None, unique=True, nullable=True)
    organization: Optional[str] = Field(default=None, nullable=True)

    # 会员与额度系统
    quota: int = Field(default=10, description="剩余分析额度")
    membership_level: int = Field(default=0, description="0: Non-member")
    membership_expires_at: Optional[datetime] = Field(default=None, nullable=True)

    # 积分系统
    points_balance: int = Field(default=0)