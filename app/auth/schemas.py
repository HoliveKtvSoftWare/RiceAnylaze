# 认证相关数据模型

import uuid
from typing import Optional # 导入 Optional
from fastapi_users import schemas

# 这个 Schema 用于读取/返回用户信息，它会包含我们自定义的字段
class UserRead(schemas.BaseUser[uuid.UUID]):
    # 确保 UserRead 包含 UserTable 中所有非敏感字段
    role: int
    quota: int
    membership_level: int
    points_balance: int
    phone_number: Optional[str] = None # 从 UserTable 添加
    organization: Optional[str] = None # 从 UserTable 添加
    # 注意：不应包含 hashed_password 等敏感信息

# 这个 Schema 用于用户注册，只包含必要的 email 和 password
class UserCreate(schemas.BaseUserCreate):
    # 如果注册时需要用户名，也在这里添加
    # username: str
    pass

# --- 新增：用于更新用户信息的 Schema ---
class UserUpdate(schemas.BaseUserUpdate):
    # 添加允许用户通过 /users/me PATCH 请求更新的字段
    phone_number: Optional[str] = None
    organization: Optional[str] = None
    # 注意：密码更新通常有单独的流程，不建议放在这里
    pass
# --- 结束新增 ---