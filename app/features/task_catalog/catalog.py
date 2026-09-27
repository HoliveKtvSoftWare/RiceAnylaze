"""Settings-backed task registry and query helpers."""

from typing import Dict, List, Optional

from app.core.config import settings
from .types import (
    LEAF_TASK_DEFAULTS, STEM_COLORS, TASK_GROUPS, TASK_GROUP_LEAF,
    TASK_GROUP_STEM, TaskSpec,
)

LEAF_MODEL_VARIANTS = [
    ("leaf", "剑叶", settings.LEAF_MODEL_PATH, "默认权重 v11-p2(exp59)：实测 IoU 最高", "native"),
    ("leaf_v11", "剑叶 · v11(exp08)", "./models_yolo/leaf-v11-exp08.pt", "实测 IoU 约 0.67", "native"),
    ("leaf_v11_head", "剑叶 · v11-head(exp12)", "./models_yolo/leaf-v11-head-exp12.pt", "含 MaskRefinement 分支，走 refine 运行时（IoU 待重测）", "fork"),
    ("leaf_v11_p2_head", "剑叶 · v11-p2-head(exp61)", "./models_yolo/leaf-v11-p2-head-exp61.pt", "含 MaskRefinement 分支，走 refine 运行时（IoU 待重测）", "fork"),
    ("leaf_our", "剑叶 · OUR-best", "./models_yolo/leaf-our-best.pt", "含 MaskRefinement 分支，走 refine 运行时；与参考输出一致（IoU 0.92）", "fork"),
    ("leaf_asf", "剑叶 · ASF-YOLO", "./models_yolo/leaf-asf-yolo.pt", "对比方法，约 73.5M 参数", "fork"),
    ("leaf_svbdet", "剑叶 · Rice-SVBDete", "./models_yolo/leaf-rice-svbdet.pt", "对比方法，约 72.9M 参数", "fork"),
    ("leaf_sod", "剑叶 · SOD-YOLO", "./models_yolo/leaf-sod-yolo.pt", "对比方法，约 70.5M 参数", "fork"),
    ("leaf_subtle", "剑叶 · Subtle-YOLO", "./models_yolo/leaf-subtle-yolo.pt", "对比方法，约 81.7M 参数", "fork"),
]


def _build_registry() -> Dict[str, TaskSpec]:
    tasks = [TaskSpec(
        key="stem", name="茎秆截面", model_path=settings.YOLO_MODEL_PATH,
        colors=STEM_COLORS, draw_first=("out",), smooth=True,
        smooth_exclude=("out",), embed_image=True, metrics="stem",
        note="水稻茎秆横切面：茎秆/空腔轮廓与大、小维管束",
    )]
    for key, name, model_path, note, runtime in LEAF_MODEL_VARIANTS:
        tasks.append(TaskSpec(key=key, name=name, model_path=model_path, note=note,
                              runtime=runtime, **LEAF_TASK_DEFAULTS))
    return {task.key: task for task in tasks}


def get_tasks() -> Dict[str, TaskSpec]:
    return _build_registry()


def _label_to_key() -> Dict[str, str]:
    """显示名 -> key。前端模型下拉框展示并回传的是 task.name。"""
    return {task.name: task.key for task in get_tasks().values()}


def resolve_task_type(value: Optional[str]) -> str:
    """把任意用户输入解析成合法的 task key。

    同时接受 task key（如 ``leaf_our``）和中文显示名（如 ``剑叶 · OUR-best``），
    因为新版前端从 /analysis/models 拿到 name 后原样回传。未知值回退 ``stem``。
    """
    if not value:
        return "stem"
    raw = str(value).strip()
    tasks = get_tasks()
    if raw.lower() in tasks:
        return raw.lower()
    return _label_to_key().get(raw, "stem")


def normalize_task_type(value: Optional[str]) -> str:
    return resolve_task_type(value)


def get_task(value: Optional[str]) -> TaskSpec:
    return get_tasks()[resolve_task_type(value)]


def is_valid_task_type(value: Optional[str]) -> bool:
    if not value:
        return False
    raw = str(value).strip()
    return raw.lower() in get_tasks() or raw in _label_to_key()


def normalize_task_group(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    key = str(value).strip().lower()
    return key if key in TASK_GROUPS else None


def is_valid_task_group(value: Optional[str]) -> bool:
    return bool(value) and str(value).strip().lower() in TASK_GROUPS


def task_types_of_group(group: Optional[str]) -> Optional[List[str]]:
    key = normalize_task_group(group)
    if not key:
        return None
    return [task.key for task in get_tasks().values() if task.group == key]


def list_tasks(group: Optional[str] = None) -> List[dict]:
    tasks = get_tasks().values()
    key = normalize_task_group(group)
    if key:
        tasks = [task for task in tasks if task.group == key]
    return [{
        "key": task.key, "name": task.name,
        "model": task.model_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        "group": task.group, "note": task.note,
    } for task in tasks]


def list_models(group: Optional[str] = None) -> List[dict]:
    """新版前端模型选择器的数据源：``[{name, path}]``。

    前端的 select 用 ``name`` 同时做 value 和展示文本，并把选中的 ``name``
    作为 ``model_name`` 回传；因此这里返回中文显示名，由
    :func:`resolve_task_type` 负责把它解析回 task key。

    额外附带 ``key``/``group`` 字段，不影响前端，便于以后按大类过滤。
    """
    tasks = get_tasks().values()
    key = normalize_task_group(group)
    if key:
        tasks = [task for task in tasks if task.group == key]
    return [{
        "name": task.name,
        "path": task.model_path,
        "key": task.key,
        "group": task.group,
    } for task in tasks]


def default_model_name(group: Optional[str] = None) -> Optional[str]:
    """默认模型：返回列表首项（stem 大类排在最前）。"""
    models = list_models(group)
    return models[0]["name"] if models else None
