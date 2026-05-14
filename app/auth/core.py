# 认证核心实现

import uuid
from fastapi_users import FastAPIUsers
from app.auth.backend import auth_backend
from app.auth.manager import get_user_manager
from app.models.user import UserTable

# 在这里创建 FastAPIUsers 实例
fastapi_users = FastAPIUsers[UserTable, uuid.UUID](
    get_user_manager,
    [auth_backend],
)