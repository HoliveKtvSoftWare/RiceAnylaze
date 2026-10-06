# -*- coding: utf-8 -*-
"""任务注册表与结构类型的对外入口。

具体族（茎秆 / 剑叶 / …）的定义在 ``families/``；各族的指标算法在
``app/domain/analysis/families/``。本包对外只暴露「族无关」的查询接口。
"""

from .registry import (
    TASK_GROUPS,
    columns_for,
    compute_metrics,
    default_model_name,
    family_of,
    get_families,
    get_task,
    get_tasks,
    is_valid_task_group,
    is_valid_task_type,
    list_models,
    list_tasks,
    normalize_task_group,
    normalize_task_type,
    resolve_task_type,
    task_types_of_group,
)
from .types import RGBA, TaskFamily, TaskSpec

__all__ = [
    "TASK_GROUPS",
    "RGBA", "TaskFamily", "TaskSpec",
    "columns_for", "compute_metrics", "default_model_name", "family_of",
    "get_families", "get_task", "get_tasks", "is_valid_task_group",
    "is_valid_task_type", "list_models", "list_tasks", "normalize_task_group",
    "normalize_task_type", "resolve_task_type", "task_types_of_group",
]
