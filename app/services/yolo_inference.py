"""Backward-compatible inference exports.

The implementation now lives under ``app.infrastructure.inference``; this
module remains importable for scripts and integrations using the old path.
"""

from app.infrastructure.inference.labelme import (
    convert_to_labelme_format,
    image_to_base64,
    prepare_preview_points,
    smooth_polygon,
    smooth_polygon_chaikin,
    smooth_polygon_midpoint,
    smooth_polygon_spline,
)
from app.infrastructure.inference.renderer import draw_polygons_on_image
from app.infrastructure.inference.runner import run_system

__all__ = [
    "convert_to_labelme_format", "draw_polygons_on_image", "image_to_base64",
    "prepare_preview_points", "run_system", "smooth_polygon",
    "smooth_polygon_chaikin", "smooth_polygon_midpoint", "smooth_polygon_spline",
]
