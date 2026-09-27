# 核心配置

from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    BACKEND_ROOT: ClassVar[Path] = Path(__file__).resolve().parents[2]
    # 通过 model_config，pydantic-settings 会自动查找并加载 .env 文件
    #
    # extra="ignore"：pydantic-settings 默认是 "forbid"，.env / 环境变量里只要出现
    # 一个本类没声明的键就会直接 ValidationError，应用起不来。.env 是逐台机器各写
    # 各的，历史键（例如旧版用过的 YOLO_MODELS）很常见，为此让整个服务无法启动
    # 不值得 —— 未声明的键一律忽略。
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 对应 .env 文件中的配置项
    # pydantic-settings 会自动进行类型检查和转换
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    STORAGE_PATH: str
    # 茎秆截面分割模型（字段名保持 YOLO_MODEL_PATH 以兼容旧配置）
    YOLO_MODEL_PATH: str
    # 剑叶分割模型（未配置时使用默认路径）
    LEAF_MODEL_PATH: str = "./models_yolo/leaf-best.pt"

    # SQL 语句日志（SQLAlchemy echo）。默认关闭：开启后每条 ORM 语句都会打进
    # uvicorn 的 stdout，既淹没访问日志，也会把文件路径、UUID 等写进日志。
    # 排查数据库问题时可在 .env 里临时设为 true。
    DB_ECHO: bool = False

    # --- 旁路（sidecar）推理配置 ---
    # 部分权重（对比方法 + 三个带 MaskRefinement 的剑叶权重）需要另一套 ultralytics，
    # 与后端环境（8.3.27）不兼容；这些任务会用下面这个解释器在子进程里执行。
    FORK_PYTHON: str = r"D:\Anaconda\envs\yolo\python.exe"
    # 子进程要用的 ultralytics 运行时（项目自有副本，含带 mask_refine 的检测头）。
    # 由 RiceAnylaze/deploy/build_refine_ultralytics.py 生成；不要指向会被人为改动的活目录。
    FORK_PROJECT: str = str(BACKEND_ROOT / ".ultra_refine")
    # 额外依赖目录（einops / timm / safetensors / basicsr 桩 等，放在工作区内不污染环境）
    FORK_PYLIBS: str = str(BACKEND_ROOT / ".pylibs")
    # 旁路脚本
    SIDECAR_SCRIPT: str = str(BACKEND_ROOT / "deploy" / "runtime" / "sidecar_infer.py")

# 创建一个全局唯一的配置实例，方便在项目其他地方导入和使用
settings = Settings()
