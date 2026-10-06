# -*- coding: utf-8 -*-
"""茎秆截面指标（纯计算）。

对应 ``TaskSpec.group == "stem"``：茎秆/空腔轮廓 + 大、小维管束。
标签体系：``out``（茎秆）、``in``（空腔）、``big``（大维管束）、``small``（小维管束）。

算法与数值口径自重构以来未改动；历史基线由
``tests/e2e/verify_refactor.py`` 逐值比对（18 组用例）。
"""

import logging
from typing import Any, Dict

from app.domain.analysis.metrics_common import (
    conversion_factor,
    diameter_from_area,
    perimeter_from_area,
    polygon_area,
)

log = logging.getLogger(__name__)


def compute(analysis_data: Dict[str, Any], unit: str, scale: float) -> Dict[str, Any]:
    """按茎秆口径计算指标。

    scale: 像素当量（µm/px）。面积按 scale²、长度按 scale 折算后，再除以
           单位换算系数换算到目标单位。
    """
    shapes = analysis_data.get("shapes", [])

    large_tail_shapes = []
    small_tail_shapes = []
    out_shapes = []
    in_shapes = []

    for shape in shapes:
        label = shape.get("label", "unknown")
        area = polygon_area(shape.get("points", []))

        if label == "big":
            large_tail_shapes.append({"area": area})
        elif label == "small":
            small_tail_shapes.append({"area": area})
        elif label == "out":
            out_shapes.append({"area": area, "points": shape.get("points", [])})
        elif label == "in":
            in_shapes.append({"area": area, "points": shape.get("points", [])})

    large_tail_count = len(large_tail_shapes)
    small_tail_count = len(small_tail_shapes)
    total_count = large_tail_count + small_tail_count

    large_tail_area_pixel = sum(shape["area"] for shape in large_tail_shapes)
    small_tail_area_pixel = sum(shape["area"] for shape in small_tail_shapes)

    stem_area_pixel = out_shapes[0]["area"] if out_shapes else 0
    cavity_area_pixel = in_shapes[0]["area"] if in_shapes else 0

    stem_diameter_pixel = diameter_from_area(stem_area_pixel)
    stem_perimeter_pixel = perimeter_from_area(stem_area_pixel)

    factor = conversion_factor(unit)

    stem_diameter = stem_diameter_pixel * scale / factor
    stem_perimeter = stem_perimeter_pixel * scale / factor

    area_scale_factor = scale ** 2
    large_tail_area = large_tail_area_pixel * area_scale_factor / (factor ** 2)
    small_tail_area = small_tail_area_pixel * area_scale_factor / (factor ** 2)
    stem_area = stem_area_pixel * area_scale_factor / (factor ** 2)
    cavity_area = cavity_area_pixel * area_scale_factor / (factor ** 2)

    stem_cavity_area_diff = stem_area - cavity_area
    large_small_area_ratio = large_tail_area / small_tail_area if small_tail_area > 0 else 0
    large_small_count_ratio = large_tail_count / small_tail_count if small_tail_count > 0 else 0
    cavity_stem_area_ratio = cavity_area / stem_area if stem_area > 0 else 0
    small_count_perimeter_ratio = small_tail_count / stem_perimeter if stem_perimeter > 0 else 0
    large_count_perimeter_cavity_ratio = large_tail_count / (
        stem_perimeter * stem_cavity_area_diff) if stem_perimeter > 0 and stem_cavity_area_diff > 0 else 0

    return {
        "largeTailCount": large_tail_count,
        "smallTailCount": small_tail_count,
        "totalCount": total_count,
        "largeTailArea": large_tail_area,
        "smallTailArea": small_tail_area,
        "stemDiameter": stem_diameter,
        "stemPerimeter": stem_perimeter,
        "cavityArea": cavity_area,
        "stemCavityAreaDiff": stem_cavity_area_diff,
        "largeSmallAreaRatio": large_small_area_ratio,
        "largeSmallCountRatio": large_small_count_ratio,
        "stemArea": stem_area,
        "cavityStemAreaRatio": cavity_stem_area_ratio,
        "smallCountPerimeterRatio": small_count_perimeter_ratio,
        "largeCountPerimeterCavityRatio": large_count_perimeter_cavity_ratio,
    }


__all__ = ["compute"]
