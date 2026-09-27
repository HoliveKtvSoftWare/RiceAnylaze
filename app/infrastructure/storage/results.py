"""Read LabelMe results and locate legacy report paths."""

import json
import os
from typing import Optional
from app.core.config import settings


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def locate_result_json(result_json_path: Optional[str], user_id: str,
                        sample_name: str) -> Optional[str]:
    """定位结果 JSON：优先使用记录里的路径，其次按旧的目录约定查找。"""
    if result_json_path and os.path.exists(result_json_path):
        return result_json_path

    candidates = [os.path.join(settings.STORAGE_PATH, user_id),
                  os.path.join("app_storage", "user_data", user_id)]
    for user_data_dir in candidates:
        if not os.path.exists(user_data_dir):
            continue

        sample_dir = os.path.join(user_data_dir, sample_name)
        if os.path.exists(sample_dir):
            for file in os.listdir(sample_dir):
                if file.endswith('.json') and (sample_name in file or file.replace('.json', '') == sample_name):
                    return os.path.join(sample_dir, file)

        for root, dirs, files in os.walk(user_data_dir):
            for file in files:
                if file.endswith('.json') and file.replace('.json', '') == sample_name:
                    return os.path.join(root, file)

        for root, dirs, files in os.walk(user_data_dir):
            for file in files:
                if file.endswith('.json') and sample_name in file:
                    return os.path.join(root, file)

    return None

# ------------------------------------------------------------------ #
# 茎秆截面指标（原有口径，勿改动计算方式）
