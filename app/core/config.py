# 核心配置

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 通过 model_config，pydantic-settings 会自动查找并加载 .env 文件
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # 对应 .env 文件中的配置项
    # pydantic-settings 会自动进行类型检查和转换
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    STORAGE_PATH: str
    YOLO_MODEL_PATH: str

# 创建一个全局唯一的配置实例，方便在项目其他地方导入和使用
settings = Settings()