# -*- coding: utf-8 -*-
"""任务注册表：聚合各族的任务定义，并提供查询。

**这是共享核心** —— 只通过 :class:`TaskFamily` 接口访问具体族，不认识任何族名。
因此新增一个分析大类只需要改 ``families/`` 目录，本文件无需改动。
"""

from typing import Dict, List, Optional

from .families import ALL_FAMILIES
from .types import TaskFamily, TaskSpec

# 已注册的分析大类；顺序即模型下拉框里各族的先后顺序。
# 兼容旧导入名（deploy 脚本 / 测试用 app.core.tasks.TASK_GROUPS）。
TASK_GROUPS = tuple(family.key for family in ALL_FAMILIES)


def get_families() -> tuple:
    """全部已注册的族。"""
    return ALL_FAMILIES


def _registered_groups() -> set:
    """已注册族 key 的集合（每次实时读取 ALL_FAMILIES）。

    刻意不在校验里用 ``TASK_GROUPS`` 常量：那是导入时的快照，与
    ``get_tasks`` / ``family_of`` 的实时视图会不一致。
    """
    return {family.key for family in ALL_FAMILIES}


def get_tasks() -> Dict[str, TaskSpec]:
    """全部任务。

    每次调用重新构造：模型路径来自 settings（.env），测试与脚本可能临时改配置，
    与重构前 ``_build_registry()`` 每次重建的行为一致。
    顺便校验「族与任务的归属关系」，族模块写错时立刻报出来。
    """
    tasks: Dict[str, TaskSpec] = {}
    for family in ALL_FAMILIES:
        for spec in family.specs():
            if spec.key in tasks:
                raise ValueError("任务 key 重复: {}（族 {} 与 {}）".format(
                    spec.key, tasks[spec.key].group, family.key))
            if spec.group != family.key:
                raise ValueError("任务 {} 的 group={} 与所属族 {} 不一致".format(
                    spec.key, spec.group, family.key))
            tasks[spec.key] = spec
    return tasks


def _default_key(tasks: Dict[str, TaskSpec]) -> str:
    """未知输入的回退目标：第一个注册族的第一个任务。

    刻意不写死具体族名 —— 共享核心里出现族名就等于重新耦合。
    """
    for spec in tasks.values():
        return spec.key
    raise RuntimeError("没有注册任何分析任务")


def resolve_task_type(value: Optional[str]) -> str:
    """把任意用户输入解析成合法的 task key。

    同时接受 task key（如 ``leaf_our``）和中文显示名（如 ``剑叶 · OUR-best``），
    因为前端从 /analysis/models 拿到 name 后会原样回传。未知值回退到默认任务。
    """
    tasks = get_tasks()
    if not value:
        return _default_key(tasks)
    raw = str(value).strip()
    if raw.lower() in tasks:
        return raw.lower()
    for spec in tasks.values():
        if spec.name == raw:
            return spec.key
    return _default_key(tasks)


def normalize_task_type(value: Optional[str]) -> str:
    return resolve_task_type(value)


def get_task(value: Optional[str]) -> TaskSpec:
    return get_tasks()[resolve_task_type(value)]


def is_valid_task_type(value: Optional[str]) -> bool:
    if not value:
        return False
    raw = str(value).strip()
    tasks = get_tasks()
    if raw.lower() in tasks:
        return True
    return any(spec.name == raw for spec in tasks.values())


# --------------------------------------------------------------------------- #
# 分析大类（族）
# --------------------------------------------------------------------------- #
def normalize_task_group(value: Optional[str]) -> Optional[str]:
    """把输入规范成合法的族 key；未知返回 None（**不**退化成"不过滤"）。"""
    if not value:
        return None
    key = str(value).strip().lower()
    return key if key in _registered_groups() else None


def is_valid_task_group(value: Optional[str]) -> bool:
    return bool(value) and str(value).strip().lower() in _registered_groups()


def family_of(value: Optional[str]) -> TaskFamily:
    """按族 key / 任务 key / 任务显示名找到所属族。

    第一个参数是 task_type 或 group 都能用：``family_of("leaf_our")`` 与
    ``family_of("leaf")`` 都返回剑叶族（``leaf`` 既是族名也是其中一个任务的 key，
    两者指向同一个族，不冲突）。
    """
    raw = str(value).strip().lower() if value else ""
    for family in ALL_FAMILIES:
        if family.key == raw:
            return family
    group = get_task(raw).group
    for family in ALL_FAMILIES:
        if family.key == group:
            return family
    raise KeyError("任务 {} 的 group={} 没有对应的已注册族".format(raw, group))


def task_types_of_group(group: Optional[str]) -> Optional[List[str]]:
    key = normalize_task_group(group)
    if not key:
        return None
    return [task.key for task in get_tasks().values() if task.group == key]


def list_tasks(group: Optional[str] = None) -> List[dict]:
    tasks = list(get_tasks().values())
    key = normalize_task_group(group)
    if key:
        tasks = [task for task in tasks if task.group == key]
    return [{
        "key": task.key, "name": task.name,
        "model": task.model_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
        "group": task.group, "note": task.note,
    } for task in tasks]


def list_models(group: Optional[str] = None) -> List[dict]:
    """前端模型选择器的数据源：``[{name, path}]``。

    前端的 select 用 ``name`` 同时做 value 和展示文本，并把选中的 ``name``
    作为 ``model_name`` 回传；因此这里返回中文显示名，由
    :func:`resolve_task_type` 负责把它解析回 task key。

    额外附带 ``key``/``group`` 字段，不影响前端，便于按大类过滤。
    """
    tasks = list(get_tasks().values())
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
    """默认模型：返回列表首项（各族按注册顺序排列）。"""
    models = list_models(group)
    return models[0]["name"] if models else None


# --------------------------------------------------------------------------- #
# 族专属内容的统一入口（导出列 / 指标算法）
# --------------------------------------------------------------------------- #
def columns_for(task_type: Optional[str]) -> Dict[str, str]:
    """该任务所属族的导出列定义（key -> 中文列名）。"""
    return family_of(task_type).columns


def compute_metrics(task_type: Optional[str], analysis_data: Dict, unit: str,
                    scale: float) -> Dict:
    """该任务所属族的指标算法。"""
    return family_of(task_type).compute_metrics(analysis_data, unit, scale)


__all__ = [
    "TASK_GROUPS",
    "get_families", "get_tasks",
    "resolve_task_type", "normalize_task_type", "get_task", "is_valid_task_type",
    "normalize_task_group", "is_valid_task_group", "family_of",
    "task_types_of_group", "list_tasks", "list_models", "default_model_name",
    "columns_for", "compute_metrics",
    "TaskSpec", "TaskFamily",
]
