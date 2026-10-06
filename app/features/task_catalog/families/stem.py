# -*- coding: utf-8 -*-
"""茎秆截面（水稻茎秆横切面）分析族。

**改动范围**：茎秆的模型清单、导出列、后处理参数都在本文件；
指标算法在同名的 ``app/domain/analysis/families/stem.py``。
不涉及剑叶的任何文件。
"""

from typing import Dict, List

from app.core.config import settings
from app.domain.analysis.families import stem as stem_metrics

from ..types import RGBA, TaskFamily, TaskSpec

# 叠加渲染配色（key = 模型输出的标签名）
STEM_COLORS: Dict[str, RGBA] = {
    "out": (255, 0, 0, 64),
    "in": (0, 255, 0, 64),
    "small": (0, 0, 255, 64),
    "big": (255, 255, 0, 64),
}

# 导出列定义。key 必须与 domain/analysis/families/stem.py::compute 的返回值一致，
# 顺序即 Excel 里的列顺序。原有口径，保持不变。
COLUMNS: Dict[str, str] = {
    "filename": "样本名称",
    "largeTailCount": "大维管束数目",
    "smallTailCount": "小维管束数目",
    "totalCount": "总维管束数目",
    "largeTailArea": "大维管束面积",
    "smallTailArea": "小维管束面积",
    "stemDiameter": "茎秆直径",
    "stemPerimeter": "茎秆周长",
    "cavityArea": "空腔面积",
    "stemCavityAreaDiff": "茎秆面积与空腔面积差值",
    "largeSmallAreaRatio": "大维管束面积与小维管束面积比值",
    "largeSmallCountRatio": "大维管束数目与小维管束数目比值",
    "stemArea": "茎秆面积",
    "cavityStemAreaRatio": "空腔面积与茎秆面积比值",
    "smallCountPerimeterRatio": "小维管束数目与茎秆周长比值",
    "largeCountPerimeterCavityRatio": "大维管束数目与茎秆周长与空腔面积差值比值",
}


def specs() -> List[TaskSpec]:
    """茎秆任务清单。

    每次调用重新构造：模型路径来自 settings（.env），测试与脚本可能临时改配置。
    这与重构前 ``get_tasks()`` 每次重建的行为一致。
    """
    return [
        TaskSpec(
            key="stem",
            name="茎秆截面",
            group="stem",
            model_path=settings.YOLO_MODEL_PATH,
            colors=STEM_COLORS,
            draw_first=("out",),
            smooth=True,
            smooth_exclude=("out",),
            embed_image=True,
            note="水稻茎秆横切面：茎秆/空腔轮廓与大、小维管束",
        )
    ]


FAMILY = TaskFamily(
    key="stem",
    label="茎秆",
    columns=COLUMNS,
    specs=specs,
    compute_metrics=stem_metrics.compute,
)
