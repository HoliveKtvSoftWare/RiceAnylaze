# 用户管理器

import uuid
from typing import Optional
from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from app.auth.db import UserTable, get_user_db
from app.core.config import settings

class UserManager(UUIDIDMixin, BaseUserManager[UserTable, uuid.UUID]):
    reset_password_token_secret = settings.SECRET_KEY
    verification_token_secret = settings.SECRET_KEY

    async def on_after_register(self, user: UserTable, request: Optional[Request] = None):
        print(f"用户 {user.id} 已注册。邮箱: {user.email}")

# 依赖注入函数：提供用户管理器实例
async def get_user_manager(user_db = Depends(get_user_db)):
    yield UserManager(user_db)