# -*- coding: utf-8 -*-
"""任务（模型）与其所属「分析大类」的结构定义。

这里只有**结构与类型**，不含任何具体族的数据 —— 族的数据在 ``families/<族>.py``。
共享核心（registry / export / statistics）只通过本文件的类型与族的接口工作，
因此永远不认识具体族；新增一个族不必改动这些文件。
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

# 颜色的 RGBA 四元组（仅类型别名，渲染层也用这个形状）
RGBA = Tuple[int, int, int, int]


@dataclass(frozen=True)
class TaskSpec:
    """一个分析任务 = 一个模型权重 + 一套后处理/推理参数。"""

    key: str                      # 任务唯一标识，也是数据库里的 task_type（勿改）
    name: str                     # 中文显示名，模型下拉框展示用
    group: str                    # 所属分析大类，须与某个 TaskFamily.key 一致（勿改）
    model_path: str
    colors: Dict[str, RGBA]
    draw_first: Tuple[str, ...] = ()
    smooth: bool = True
    smooth_exclude: Tuple[str, ...] = ()
    embed_image: bool = True
    auto_scale: bool = True
    outline_labels: Tuple[str, ...] = ()
    preview_smooth: bool = False
    preserve_mask_topology: bool = False
    validate_side_bundles: bool = False
    predict_imgsz: Optional[int] = None
    conf: float = 0.25
    iou: float = 0.7
    retina_masks: bool = False
    runtime: str = "native"       # "native"=进程内推理 / "fork"=旁路子进程
    note: str = ""                # 展示给用户的说明

    @property
    def metrics(self) -> str:
        """**已废弃别名**，等价于 :attr:`group`。

        旧字段名叫 ``metrics``（"用哪套指标口径"），现在统一叫 ``group``（分析大类）。
        保留这个只读别名，是为了让 2026-09-22 的历史快照
        （``tests/e2e/verify_refactor.py`` 的基线比对）和仓库外的旧脚本继续可用。
        新代码请直接用 ``group``；确认无引用后即可删除。
        """
        return self.group


@dataclass(frozen=True, eq=False)
class TaskFamily:
    """一个分析大类的全部「族专属」内容。

    这是共享核心与具体族之间**唯一的接口**：

    * ``key``   —— 必须与 ``TaskSpec.group``、以及 HTTP 的 ``group`` 查询参数一致
      （数据库历史数据与前端契约都依赖这个字符串，不能改）
    * ``label`` —— 中文名，前端与错误提示直接使用
    * ``columns``        —— 导出列定义（key -> 中文列名）
    * ``specs``          —— 该族全部任务（每次调用重新构造，见各族注释）
    * ``compute_metrics``—— 指标算法：``(analysis_data, unit, scale) -> {列 key: 数值}``

    相等与哈希**只按 key**：族是注册表里的单例，且 ``columns`` 是 dict，
    不能用字段整体做哈希（dataclass 默认生成的 __hash__ 会在放进 set/dict 时炸掉）。
    """

    key: str
    label: str
    columns: Dict[str, str]
    specs: Callable[[], List[TaskSpec]]
    compute_metrics: Callable[[Dict[str, Any], str, float], Dict[str, Any]]

    def __hash__(self) -> int:
        return hash(self.key)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TaskFamily) and other.key == self.key


__all__ = ["RGBA", "TaskSpec", "TaskFamily"]
