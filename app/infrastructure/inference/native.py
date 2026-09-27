"""Native ultralytics model loading and prediction."""

import logging

log = logging.getLogger(__name__)


def load_model(model_path):
    import os

    if not os.path.isfile(model_path):
        raise FileNotFoundError(
            f"模型文件不存在: {model_path}\n"
            f"请检查任务注册表（app/features/task_catalog/catalog.py）中的 model_path，"
            f"或确认该权重文件已放置到正确路径。"
        )

    import torch
    from ultralytics import YOLO

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log.info("using device: %s", device)
    return YOLO(model_path).to(device)


def predict(model, image_path, imgsz=640, conf=0.25, iou=0.7, retina_masks=False):
    kwargs = {
        "show": False,
        "save": False,
        "visualize": False,
        "conf": conf,
        "iou": iou,
        "retina_masks": retina_masks,
    }
    if imgsz:
        kwargs["imgsz"] = imgsz
    return model(image_path, **kwargs)


def run_prediction(model_path, image_path, imgsz=640, conf=0.25, iou=0.7, retina_masks=False):
    """Load a model and execute one prediction; kept small for sidecar use/tests."""
    return predict(load_model(model_path), image_path, imgsz, conf, iou, retina_masks)
