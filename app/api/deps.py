"""Shared FastAPI dependencies for the application-facing routers."""

from app.auth.core import fastapi_users
from app.infrastructure.database.session import get_async_session

current_active_user = fastapi_users.current_user(active=True)

__all__ = ["current_active_user", "get_async_session"]
