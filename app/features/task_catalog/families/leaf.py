# -*- coding: utf-8 -*-
"""剑叶（水稻剑叶）分析族。

**改动范围**：剑叶的模型清单、导出列、后处理参数都在本文件；
指标算法在同名的 ``app/domain/analysis/families/leaf.py``。
不涉及茎秆的任何文件。

剑叶下有多个权重变体（自有权重 + 对比方法），它们的**列口径完全相同**，
因此同属一个族；差异只在模型路径与运行时（native / fork）。
"""

from typing import Dict, List, Tuple

from app.core.config import settings
from app.domain.analysis.families import leaf as leaf_metrics

from ..types import RGBA, TaskFamily, TaskSpec

# 叠加渲染配色（key = 模型输出的标签名）
LEAF_COLORS: Dict[str, RGBA] = {
    "body1": (0, 110, 255, 235),
    "side1": (0, 210, 90, 235),
    "side2": (0, 190, 220, 235),
    "body2": (185, 0, 235, 235),
    "body_big": (255, 0, 0, 150),
    "body1_small": (255, 140, 0, 145),
    "body2_small": (255, 0, 255, 145),
    "side1_big": (200, 0, 60, 160),
    "side1_small": (255, 215, 0, 150),
    "side2_big": (0, 120, 0, 160),
    "side2_small": (150, 255, 110, 150),
}

# 族内所有任务共用的推理 / 后处理参数（差异只在 model_path 与 runtime）
LEAF_TASK_DEFAULTS = dict(
    colors=LEAF_COLORS,
    draw_first=("body1", "side1", "side2", "body2"),
    smooth=False,
    smooth_exclude=(),
    embed_image=False,
    auto_scale=True,
    outline_labels=("body1", "side1", "side2", "body2"),
    preview_smooth=True,
    preserve_mask_topology=True,
    validate_side_bundles=True,
    predict_imgsz=None,
    conf=0.25,
    iou=0.45,
    retina_masks=True,
)

# (key, 显示名, 权重路径, 说明, 运行时)
#   native = 主环境 ultralytics 可直接加载
#   fork   = 含 MaskRefinement 分支或对比方法，需要旁路的另一套 ultralytics
LEAF_MODEL_VARIANTS: List[Tuple[str, str, str, str, str]] = [
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

# 导出列定义。key 必须与 domain/analysis/families/leaf.py::compute 的返回值一致。
#
# 相对参考脚本 4-30-2026侧脉代码.py 的修正：
#   1) 截面面积不再把完全位于主脉内部的空腔重复计入，另给出「组织净面积」；
#   2) 周长改为直接使用多边形周长，不再做「合并周长减连接长度」的魔改，
#      并按文档口径额外提供侧脉周长÷2。
COLUMNS: Dict[str, str] = {
    "filename": "样本名称",
    "scaleUmPerPx": "比例尺(µm/px)",
    "sectionArea": "截面面积(含腔)",
    "tissueArea": "组织净面积",
    "body1Area": "主脉面积",
    "body2Area": "空腔面积",
    "side1Area": "侧脉1面积",
    "side2Area": "侧脉2面积",
    "body1Perimeter": "主脉周长",
    "body2Perimeter": "空腔周长",
    "side1Perimeter": "侧脉1周长",
    "side2Perimeter": "侧脉2周长",
    "side1HalfPerimeter": "侧脉1周长÷2",
    "side2HalfPerimeter": "侧脉2周长÷2",
    "bodyBigCount": "主脉大维管束数目",
    "bodyBigTotalArea": "主脉大维管束总面积",
    "bodyBigAvgArea": "主脉大维管束平均面积",
    "bodySmallCount": "主脉小维管束数目",
    "bodySmallTotalArea": "主脉小维管束总面积",
    "bodySmallAvgArea": "主脉小维管束平均面积",
    "cavitySmallCount": "空腔小维管束数目",
    "cavitySmallTotalArea": "空腔小维管束总面积",
    "cavitySmallAvgArea": "空腔小维管束平均面积",
    "side1BigCount": "侧脉1大维管束数目",
    "side1BigTotalArea": "侧脉1大维管束总面积",
    "side1BigAvgArea": "侧脉1大维管束平均面积",
    "side1SmallCount": "侧脉1小维管束数目",
    "side1SmallTotalArea": "侧脉1小维管束总面积",
    "side1SmallAvgArea": "侧脉1小维管束平均面积",
    "side2BigCount": "侧脉2大维管束数目",
    "side2BigTotalArea": "侧脉2大维管束总面积",
    "side2BigAvgArea": "侧脉2大维管束平均面积",
    "side2SmallCount": "侧脉2小维管束数目",
    "side2SmallTotalArea": "侧脉2小维管束总面积",
    "side2SmallAvgArea": "侧脉2小维管束平均面积",
}


def specs() -> List[TaskSpec]:
    """剑叶任务清单（每次调用重新构造，理由同茎秆族）。"""
    return [
        TaskSpec(
            key=key,
            name=name,
            group="leaf",
            model_path=model_path,
            note=note,
            runtime=runtime,
            **LEAF_TASK_DEFAULTS,
        )
        for key, name, model_path, note, runtime in LEAF_MODEL_VARIANTS
    ]


FAMILY = TaskFamily(
    key="leaf",
    label="剑叶",
    columns=COLUMNS,
    specs=specs,
    compute_metrics=leaf_metrics.compute,
)
