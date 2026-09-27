"""唯一的数据库引擎、会话和启动时结构检查入口。

异步 HTTP 请求和同步 worker 共用这里创建的两个 engine。业务代码只应依赖
``get_async_session``、``engine`` 或 ``sync_engine``，不应自行创建连接池。
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, create_engine as create_sync_engine

from app.core.config import settings
from app.infrastructure.database.migrations import apply_light_migrations

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DB_ECHO, future=True)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

sync_engine = create_sync_engine(
    settings.DATABASE_URL.replace("+asyncpg", ""),
    echo=False,
    future=True,
)


async def create_db_and_tables() -> None:
    """创建缺失表并补齐已登记的兼容列，不删除任何数据。"""
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await apply_light_migrations(conn)


async def get_async_session():
    """FastAPI 数据库依赖；所有 HTTP 路由和认证共用这个生成器。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
