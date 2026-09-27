# 认证数据库实现

from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase # <--- 修正这一行
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database.session import get_async_session
from app.models.user import UserTable

async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, UserTable)
