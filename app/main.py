from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import os
from app.infrastructure.database.session import create_db_and_tables
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.api.routers import auth, analysis, excel, export
from app.features.analysis import queue as analysis_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("应用启动...")
    await create_db_and_tables()
    # 拉起唯一的队列 worker 线程（推理串行执行，见 app/features/analysis/queue.py）
    analysis_queue.start_worker()
    # 队列不跨重启：清理上一进程遗留的 queued / processing 记录
    # （processing 且原图还在的会自动重新排队）
    analysis_queue.requeue_pending_on_startup()
    yield
    # 先停队列再关应用；正在跑的推理不会被打断
    analysis_queue.stop_worker()
    print("应用关闭...")

app = FastAPI(lifespan=lifespan)

# CORS配置
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

# 挂载认证和用户管理路由
app.include_router(auth.router)

# 挂载分析路由
app.include_router(analysis.router, prefix="/api/analysis", tags=["Analysis"])

# 挂载Excel导出路由
app.include_router(excel.router, prefix="/api/excel", tags=["Excel"])

# 挂载JSON导出路由
app.include_router(export.router, tags=["Export"])

# 配置静态文件
static_dir = settings.STORAGE_PATH
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 根路径
@app.get("/")
def read_root():
    return {"Hello": "World"}
