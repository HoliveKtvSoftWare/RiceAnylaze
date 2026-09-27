"""Native segmentation runner and output orchestration."""

import json
import logging
import os

import numpy as np
from PIL import Image

from app.domain.geometry.mask_geometry import reassign_side_bundle_labels, resize_binary_mask

from . import native
from .labelme import convert_to_labelme_format
from .renderer import draw_polygons_on_image

log = logging.getLogger(__name__)


def run_system(model_path, image_path, output_path, output_basename,
               smooth=True, smooth_method="chaikin", smooth_iterations=2,
               colors=None, draw_first=("out",), embed_image=True, smooth_exclude=("out",),
               outline_labels=(), imgsz=640, conf=0.25, iou=0.7, retina_masks=False,
               preserve_mask_topology=False, validate_side_bundles=False,
               preview_smooth=False):
    """Run YOLO segmentation, write LabelMe JSON and annotated JPG."""
    log.info("starting inference: model=%s image=%s", model_path, image_path)
    model = native.load_model(model_path)
    results = native.predict(model, image_path, imgsz=imgsz, conf=conf, iou=iou,
                             retina_masks=retina_masks)
    image = Image.open(image_path)
    masks_list, labels_list, raw_masks_list, shape_flags_list = [], [], [], []
    result = None
    for result in results:
        boxes = result.boxes
        masks = result.masks
        raw_masks = {}
        corrections = {}
        if masks is None:
            log.warning("image %s had no masks", image_path)
            masks_xy, label_names = [], []
        else:
            masks_xy = masks.xy
            label_names = [result.names[int(value)] for value in boxes.cls]
            if preserve_mask_topology:
                for index, label_name in enumerate(label_names):
                    if label_name in outline_labels:
                        raw_masks[index] = resize_binary_mask(masks.data[index], image.size)
            if validate_side_bundles:
                region_masks = {}
                for side_label in ("side1", "side2"):
                    side_parts = [raw_masks[index] for index, label_name in enumerate(label_names)
                                  if label_name == side_label and index in raw_masks]
                    if side_parts:
                        region_masks[side_label] = np.logical_or.reduce(side_parts).astype(np.uint8)
                label_names, corrections = reassign_side_bundle_labels(
                    label_names, boxes.xyxy.detach().cpu().numpy(), region_masks)
        masks_list.append(masks_xy)
        labels_list.append(label_names)
        raw_masks_list.append(raw_masks)
        shape_flags_list.append([{
            "side_reassigned_from": corrections[index],
            "side_reassigned_by": "region_containment",
        } if index in corrections else {} for index in range(len(label_names))])

    if result is None:
        names = {}
    else:
        names = result.names
    labelme_data = convert_to_labelme_format(
        image_path, image.size, masks_list, labels_list, names,
        smooth=smooth, smooth_method=smooth_method, smooth_iterations=smooth_iterations,
        embed_image=embed_image, smooth_exclude=smooth_exclude,
        raw_masks_list=raw_masks_list,
        topology_labels=outline_labels if preserve_mask_topology else (),
        shape_flags_list=shape_flags_list,
    )
    os.makedirs(output_path, exist_ok=True)
    json_output_path = os.path.join(output_path, f"{output_basename}.json")
    with open(json_output_path, "w") as json_file:
        json.dump(labelme_data, json_file, indent=4)

    output_image = draw_polygons_on_image(
        image, labelme_data["shapes"], colors=colors, draw_first=draw_first,
        outline_labels=outline_labels, preview_smooth=preview_smooth,
        smooth_method=smooth_method, smooth_iterations=smooth_iterations,
    )
    output_image_path = os.path.join(output_path, f"{output_basename}.jpg")
    output_image.save(output_image_path)
    return output_image_path, json_output_path
