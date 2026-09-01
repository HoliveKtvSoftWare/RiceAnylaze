# app/database/session.py
"""
数据库会话管理
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from app.core.config import settings

# 1. 创建异步数据库引擎
# 这个引擎是 SQLAlchemy 与数据库沟通的核心接口
engine = create_async_engine(settings.DATABASE_URL, echo=True, future=True)

# 2. 创建异步会话工厂（新增）
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# 3. 定义一个函数，用于在应用启动时创建所有数据表
async def create_db_and_tables():
    # 注意：这里我们使用 'async with' 语法
    async with engine.begin() as conn:
        # await conn.run_sync(SQLModel.metadata.drop_all) # 如果需要，可以在启动时清空数据表
        await conn.run_sync(SQLModel.metadata.create_all)

# 4. 异步数据库会话依赖（新增）
async def get_async_session():
    """
    获取异步数据库会话
    用于 FastAPI 依赖注入
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()