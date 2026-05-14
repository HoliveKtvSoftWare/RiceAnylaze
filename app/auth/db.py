# 认证数据库实现

from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase # <--- 修正这一行
from typing import AsyncGenerator
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.database.session import engine
from app.models.user import UserTable

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session

async def get_user_db(session: AsyncSession = Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, UserTable)