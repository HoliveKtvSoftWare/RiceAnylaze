"""Pure task specification types and rendering defaults."""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

RGBA = Tuple[int, int, int, int]
TASK_GROUP_STEM = "stem"
TASK_GROUP_LEAF = "leaf"
TASK_GROUPS = (TASK_GROUP_STEM, TASK_GROUP_LEAF)

STEM_COLORS: Dict[str, RGBA] = {
    "out": (255, 0, 0, 64), "in": (0, 255, 0, 64),
    "small": (0, 0, 255, 64), "big": (255, 255, 0, 64),
}
LEAF_COLORS: Dict[str, RGBA] = {
    "body1": (0, 110, 255, 235), "side1": (0, 210, 90, 235),
    "side2": (0, 190, 220, 235), "body2": (185, 0, 235, 235),
    "body_big": (255, 0, 0, 150), "body1_small": (255, 140, 0, 145),
    "body2_small": (255, 0, 255, 145), "side1_big": (200, 0, 60, 160),
    "side1_small": (255, 215, 0, 150), "side2_big": (0, 120, 0, 160),
    "side2_small": (150, 255, 110, 150),
}


@dataclass(frozen=True)
class TaskSpec:
    key: str
    name: str
    model_path: str
    colors: Dict[str, RGBA]
    draw_first: Tuple[str, ...] = ()
    smooth: bool = True
    smooth_exclude: Tuple[str, ...] = ()
    embed_image: bool = True
    metrics: str = "stem"
    auto_scale: bool = True
    outline_labels: Tuple[str, ...] = ()
    preview_smooth: bool = False
    preserve_mask_topology: bool = False
    validate_side_bundles: bool = False
    predict_imgsz: Optional[int] = None
    conf: float = 0.25
    iou: float = 0.7
    retina_masks: bool = False
    runtime: str = "native"
    note: str = ""

    @property
    def group(self) -> str:
        return TASK_GROUP_LEAF if self.metrics == "leaf" else TASK_GROUP_STEM


LEAF_TASK_DEFAULTS = dict(
    colors=LEAF_COLORS,
    draw_first=("body1", "side1", "side2", "body2"), smooth=False,
    smooth_exclude=(), embed_image=False, metrics="leaf", auto_scale=True,
    outline_labels=("body1", "side1", "side2", "body2"), preview_smooth=True,
    preserve_mask_topology=True, validate_side_bundles=True, predict_imgsz=None,
    conf=0.25, iou=0.45, retina_masks=True,
)
