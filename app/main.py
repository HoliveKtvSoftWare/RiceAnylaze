from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import os
from app.auth.backend import auth_backend
from app.auth.manager import get_user_manager
from app.models.user import UserTable
from app.database.session import create_db_and_tables
from app.auth.schemas import UserCreate, UserRead, UserUpdate
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.endpoints import analysis_router as analysis_router
from app.api.endpoints import excel_router as excel_router
from app.api.endpoints import export_router  # 🆕 新增这行导入
from app.auth.core import fastapi_users


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("应用启动...")
    await create_db_and_tables()
    yield
    print("应用关闭...")

app = FastAPI(lifespan=lifespan)

# ORS配置
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载认证路由
app.include_router(
    fastapi_users.get_auth_router(auth_backend), prefix="/api/auth/jwt", tags=["auth"]
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/api/auth",
    tags=["auth"],
)

# 挂载用户管理路由
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)

# 挂载分析路由
app.include_router(analysis_router.router, prefix="/api/analysis", tags=["Analysis"])

# 挂载Excel导出路由
app.include_router(excel_router.router, prefix="/api/excel", tags=["Excel"])

# 🆕 挂载JSON导出路由（新增这行）
app.include_router(export_router.router, tags=["Export"])

# 配置静态文件
static_dir = settings.STORAGE_PATH
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 根路径
@app.get("/")
def read_root():
    return {"Hello": "World"}