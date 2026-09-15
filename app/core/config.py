# 核心配置

import json
import logging
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    STORAGE_PATH: str
    YOLO_MODEL_PATH: str = "./models_yolo/yolov8s-1.pt"
    YOLO_MODELS: str = '{"yolov8s-1": "./models_yolo/yolov8s-1.pt"}'

    def get_models_map(self) -> dict:
        try:
            models = json.loads(self.YOLO_MODELS)
        except (json.JSONDecodeError, TypeError):
            log.warning("YOLO_MODELS 解析失败，回退到默认模型。")
            models = {}
        if not models:
            models = {"default": self.YOLO_MODEL_PATH}
        return models

    def get_model_path(self, model_name: Optional[str]) -> str:
        models = self.get_models_map()
        if model_name and model_name in models:
            return models[model_name]
        log.warning(f"未知模型 '{model_name}'，回退到默认模型 {self.YOLO_MODEL_PATH}")
        return self.YOLO_MODEL_PATH

    def get_available_models(self) -> list:
        models = self.get_models_map()
        return [
            {"name": name, "path": path}
            for name, path in models.items()
        ]


settings = Settings()