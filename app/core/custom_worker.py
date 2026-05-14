# 自定义工作进程

from rq.worker import SimpleWorker

# ------------------ 核心修改 ------------------
# 因为您环境的 rq 版本较旧，没有 NoDeathPenalty，
# 所以我们在这里自己定义一个功能完全相同的“虚拟”类。
# 它是一个什么也不做的上下文管理器，可以安全地禁用超时功能。
class NoDeathPenalty:
    def __init__(self, *args, **kwargs):
        pass
    def __enter__(self):
        pass
    def __exit__(self, exc_type, exc_value, traceback):
        pass
# -----------------------------------------------

class WindowsWorker(SimpleWorker):
    """
    这是一个自定义的 Worker，专为 Windows 环境设计。
    它通过使用我们自己创建的 NoDeathPenalty 类，
    彻底禁用了在 Windows 上不兼容的超时机制。
    """
    # 使用我们自己创建的类
    death_penalty_class = NoDeathPenalty