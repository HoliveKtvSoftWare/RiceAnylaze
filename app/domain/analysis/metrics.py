"""Stem and leaf metrics, independent of HTTP, databases and file storage."""

import math
import logging
from typing import List, Dict, Any, Tuple

from app.domain.geometry.mask_geometry import topology_geometry

log = logging.getLogger(__name__)

# ==================== 剑叶模型的标签体系（11 类 notail 版） ====================
# 区域标签：主脉 / 侧脉1 / 侧脉2 / 空腔（每个样本应各出现一次）
LEAF_REGION_LABELS = ("body1", "side1", "side2", "body2")
# 维管束标签：主脉大/小、空腔小、两条侧脉的大/小
LEAF_BUNDLE_LABELS = ("body_big", "body1_small", "body2_small",
                      "side1_big", "side1_small", "side2_big", "side2_small")

# 图内比例尺线条所代表的物理长度（µm）
SCALE_BAR_UM = 500.0


def polygon_area(points: List[List[float]]) -> float:
    """鞋带（格林）公式计算多边形面积，与 cv2.contourArea 等价。"""
    n = len(points)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0


def polygon_perimeter(points: List[List[float]]) -> float:
    """多边形周长：逐段弦长求和（含闭合段），与 cv2.arcLength(..., True) 等价。

    注意：周长完全由顶点决定，对标注/预测轮廓的点密度敏感；
    模型输出的轮廓点很密，与人工标注的稀疏多边形不可直接比较。
    """
    n = len(points)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        j = (i + 1) % n
        total += math.hypot(points[j][0] - points[i][0], points[j][1] - points[i][1])
    return total



class AnalysisMetrics:
    unit_conversion = {"um": 1.0, "μm": 1.0, "mm": 1000.0, "cm": 10000.0}

    def _load_stem_metrics(self, analysis_data: Dict[str, Any], unit: str, scale: float) -> Dict[str, Any]:
        shapes = analysis_data.get("shapes", [])

        large_tail_shapes = []
        small_tail_shapes = []
        out_shapes = []
        in_shapes = []

        for shape in shapes:
            label = shape.get("label", "unknown")
            area = self._calculate_shape_area(shape.get("points", []))

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

        stem_diameter_pixel = self._calculate_diameter_from_area(stem_area_pixel)
        stem_perimeter_pixel = self._calculate_perimeter_from_area(stem_area_pixel)

        conversion_factor = self.unit_conversion.get(unit, 1.0)

        stem_diameter = stem_diameter_pixel * scale / conversion_factor
        stem_perimeter = stem_perimeter_pixel * scale / conversion_factor

        area_scale_factor = scale ** 2
        large_tail_area = large_tail_area_pixel * area_scale_factor / (conversion_factor ** 2)
        small_tail_area = small_tail_area_pixel * area_scale_factor / (conversion_factor ** 2)
        stem_area = stem_area_pixel * area_scale_factor / (conversion_factor ** 2)
        cavity_area = cavity_area_pixel * area_scale_factor / (conversion_factor ** 2)

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
            "largeCountPerimeterCavityRatio": large_count_perimeter_cavity_ratio
        }

    # ------------------------------------------------------------------ #
    # 剑叶指标（11 类自洽子集）
    # ------------------------------------------------------------------ #
    def _load_leaf_metrics(self, analysis_data: Dict[str, Any], unit: str, k: float) -> Dict[str, Any]:
        """计算剑叶指标。

        k: 像素当量（µm/px），由 load_analysis_data 统一解析后传入
           （优先图内 500µm 比例尺自动识别，失败回退请求参数）。
        """
        shapes = analysis_data.get("shapes", [])

        region_metrics: Dict[str, Tuple[float, float]] = {}   # label -> (面积px², 周长px)
        legacy_regions: Dict[str, List[dict]] = {}
        topology_regions: Dict[str, Dict[Any, List[dict]]] = {}
        bundle_areas: Dict[str, List[float]] = {}

        for shape in shapes:
            label = shape.get("label", "unknown")
            points = shape.get("points", [])

            if label in LEAF_REGION_LABELS:
                flags = shape.get("flags") or {}
                if flags.get("mask_topology"):
                    group_id = shape.get("group_id")
                    group_key = group_id if group_id is not None else "topology"
                    topology_regions.setdefault(label, {}).setdefault(group_key, []).append(shape)
                else:
                    legacy_regions.setdefault(label, []).append(shape)
            elif label in LEAF_BUNDLE_LABELS:
                bundle_areas.setdefault(label, []).append(self._calculate_shape_area(points))
            else:
                log.debug(f"剑叶结果中忽略未知标签: {label}")

        for label in LEAF_REGION_LABELS:
            candidates = [
                topology_geometry(group_shapes)
                for group_shapes in topology_regions.get(label, {}).values()
            ]
            candidates.extend(
                (self._calculate_shape_area(shape.get("points", [])),
                 polygon_perimeter(shape.get("points", [])))
                for shape in legacy_regions.get(label, [])
            )
            if candidates:
                region_metrics[label] = max(candidates, key=lambda item: item[0])
                if len(candidates) > 1:
                    log.warning(f"剑叶结果中区域标签 {label} 出现 {len(candidates)} 个实例，保留面积最大者")
            else:
                log.warning(f"剑叶结果中缺少区域标签 {label}，相关指标按 0 处理")

        if not k or k <= 0:
            k = 1.0
            log.warning("像素当量无效，按 1 µm/px 处理")

        conversion_factor = self.unit_conversion.get(unit, 1.0)
        area_factor = (k ** 2) / (conversion_factor ** 2)
        length_factor = k / conversion_factor

        def region_area(label: str) -> float:
            return region_metrics.get(label, (0.0, 0.0))[0]

        def region_perimeter(label: str) -> float:
            return region_metrics.get(label, (0.0, 0.0))[1]

        def bundle_stats(label: str) -> Tuple[int, float, float]:
            areas = bundle_areas.get(label, [])
            count = len(areas)
            total_px = sum(areas)
            total = total_px * area_factor
            avg = (total_px / count) * area_factor if count else 0.0
            return count, total, avg

        body1_area = region_area("body1")
        body2_area = region_area("body2")
        side1_area = region_area("side1")
        side2_area = region_area("side2")

        side1_perimeter = region_perimeter("side1") * length_factor
        side2_perimeter = region_perimeter("side2") * length_factor

        body_big_count, body_big_total, body_big_avg = bundle_stats("body_big")
        body_small_count, body_small_total, body_small_avg = bundle_stats("body1_small")
        cavity_small_count, cavity_small_total, cavity_small_avg = bundle_stats("body2_small")
        side1_big_count, side1_big_total, side1_big_avg = bundle_stats("side1_big")
        side1_small_count, side1_small_total, side1_small_avg = bundle_stats("side1_small")
        side2_big_count, side2_big_total, side2_big_avg = bundle_stats("side2_big")
        side2_small_count, side2_small_total, side2_small_avg = bundle_stats("side2_small")

        return {
            "scaleUmPerPx": round(k, 4),
            # 修正：空腔完全位于主脉内部，截面面积不再重复计入
            "sectionArea": (body1_area + side1_area + side2_area) * area_factor,
            "tissueArea": max(0.0, body1_area - body2_area + side1_area + side2_area) * area_factor,
            "body1Area": body1_area * area_factor,
            "body2Area": body2_area * area_factor,
            "side1Area": side1_area * area_factor,
            "side2Area": side2_area * area_factor,
            "body1Perimeter": region_perimeter("body1") * length_factor,
            "body2Perimeter": region_perimeter("body2") * length_factor,
            "side1Perimeter": side1_perimeter,
            "side2Perimeter": side2_perimeter,
            "side1HalfPerimeter": side1_perimeter / 2.0,
            "side2HalfPerimeter": side2_perimeter / 2.0,
            "bodyBigCount": body_big_count,
            "bodyBigTotalArea": body_big_total,
            "bodyBigAvgArea": body_big_avg,
            "bodySmallCount": body_small_count,
            "bodySmallTotalArea": body_small_total,
            "bodySmallAvgArea": body_small_avg,
            "cavitySmallCount": cavity_small_count,
            "cavitySmallTotalArea": cavity_small_total,
            "cavitySmallAvgArea": cavity_small_avg,
            "side1BigCount": side1_big_count,
            "side1BigTotalArea": side1_big_total,
            "side1BigAvgArea": side1_big_avg,
            "side1SmallCount": side1_small_count,
            "side1SmallTotalArea": side1_small_total,
            "side1SmallAvgArea": side1_small_avg,
            "side2BigCount": side2_big_count,
            "side2BigTotalArea": side2_big_total,
            "side2BigAvgArea": side2_big_avg,
            "side2SmallCount": side2_small_count,
            "side2SmallTotalArea": side2_small_total,
            "side2SmallAvgArea": side2_small_avg,
        }

    # ------------------------------------------------------------------ #
    # 几何工具
    # ------------------------------------------------------------------ #
    def _calculate_shape_area(self, points: List[List[float]]) -> float:
        if len(points) < 3:
            return 0.0

        area = 0.0
        n = len(points)
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]

        return abs(area) / 2.0

    def _calculate_diameter_from_area(self, area: float) -> float:
        if area <= 0:
            return 0.0
        return 2 * math.sqrt(area / math.pi)

    def _calculate_perimeter_from_area(self, area: float) -> float:
        if area <= 0:
            return 0.0
        return 2 * math.pi * math.sqrt(area / math.pi)

    # ------------------------------------------------------------------ #
    # 生成 Excel
    # ------------------------------------------------------------------ #
