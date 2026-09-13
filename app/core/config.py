# 核心配置

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    STORAGE_PATH: str
    YOLO_MODEL_PATH: str

# 创建一个全局唯一的配置实例，方便在项目其他地方导入和使用
settings = Settings()