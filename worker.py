import sys
from redis import Redis
from app.core.custom_worker import WindowsWorker as Worker

# 将 'app' 目录添加到 Python 路径
from pathlib import Path
sys.path.append(str(Path(__file__).parent.joinpath('app')))

from app.core.config import settings

listen = ['default']
redis_conn = Redis.from_url(settings.REDIS_URL)

if __name__ == '__main__':
    print("启动自定义 RQ Worker (完全 Windows 兼容模式)...")

    # 这里的用法保持不变，但现在的 'Worker' 是我们自己的 WindowsWorker
    worker = Worker(listen, connection=redis_conn)

    # 启动 Worker
    worker.work()