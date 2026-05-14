# YOLO 推理服务

import os
import json
import base64
import logging  # 1. 导入 logging 模块
from PIL import Image, ImageDraw
from ultralytics import YOLO
import torch

# 2. 设置一个日志记录器
log = logging.getLogger(__name__)

# --- 您提供的所有辅助函数 (image_to_base64, is_point_inside_polygon, ...) ---
# --- 它们都非常棒，我们几乎不需要改动 ---

def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def is_point_inside_polygon(x, y, polygon):
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        if ((polygon[i][1] > y) != (polygon[j][1] > y)) and \
                (x < polygon[i][0] + (polygon[j][0] - polygon[i][0]) * (y - polygon[i][1]) / (
                        polygon[j][1] - polygon[i][1])):
            inside = not inside
        j = i
    return inside


def convert_to_labelme_format(image_path, image_size, masks_list, labels_list, names):
    image_data = image_to_base64(image_path)
    labelme_format = {
        "version": "5.0.1",
        "flags": {},
        "shapes": [],
        "imagePath": os.path.basename(image_path),
        "imageData": image_data,
        "imageHeight": image_size[1],
        "imageWidth": image_size[0]
    }
    for i, (masks_xy, boxes_cls) in enumerate(zip(masks_list, labels_list)):
        for j, polygon in enumerate(masks_xy):
            cls = int(boxes_cls[j])
            points = [(float(point[0]), float(point[1])) for point in polygon]
            shape = {
                "label": names[int(cls)],
                "points": points,
                "group_id": None,
                "shape_type": "polygon",
                "flags": {}
            }
            labelme_format["shapes"].append(shape)
    return labelme_format


def draw_polygons_on_image(image, shapes):
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    colors = {
        "out": (255, 0, 0, 64),
        "in": (0, 255, 0, 64),
        "small": (0, 0, 255, 64),
        "big": (255, 255, 0, 64),
    }
    for shape in shapes:
        if shape['label'] == 'out':
            points = shape['points']
            color = colors.get('out', (255, 255, 0, 64))
            if len(points) >= 2:
                draw.polygon(points, fill=color)
    for shape in shapes:
        if shape['label'] != 'out':
            points = shape['points']
            color = colors.get(shape['label'], (255, 255, 0, 64))
            if len(points) >= 2:
                draw.polygon(points, fill=color)
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    return image.convert("RGB")

# --- run_system 函数的核心修改 ---

def run_system(model_path, image_path, output_path, output_basename):
    try:
        log.info(f"开始推理任务... 模型: {model_path}, 图片: {image_path}")
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        log.info(f"使用的设备: {device}")
        model = YOLO(model_path).to(device)

        log.info(f"模型加载成功，开始对 {image_path} 进行推理...")
        results = model(image_path, show=False, save=False, visualize=False)

        image = Image.open(image_path)
        # image_fullname = os.path.basename(image_path) # 不再需要从路径获取
        # image_name = os.path.splitext(image_fullname)[0] # 使用传递进来的 basename

        masks_list = []
        labels_list = []

        for result in results:
            boxes = result.boxes
            masks = result.masks
            if masks is None:
                log.warning(f"图片 {image_path} 未检测到任何掩码 (masks)。")
                masks_xy = []
            else:
                masks_xy = masks.xy
            boxes_cls = boxes.cls
            masks_list.append(masks_xy)
            labels_list.append(boxes_cls)

        names = result.names
        image_size = image.size

        log.info("推理完成，开始生成 LabelMe JSON...")
        labelme_data = convert_to_labelme_format(image_path, image_size, masks_list, labels_list, names)

        # 使用 output_basename 命名 JSON 文件
        json_output_path = os.path.join(output_path, f"{output_basename}.json")
        with open(json_output_path, "w") as json_file:
            json.dump(labelme_data, json_file, indent=4)
        log.info(f"JSON 文件已保存到: {json_output_path}")

        log.info("开始绘制带掩膜的图片...")
        output_image = draw_polygons_on_image(image, labelme_data["shapes"])
        # 使用 output_basename 命名图片文件
        output_image_path = os.path.join(output_path, f"{output_basename}.jpg")
        output_image.save(output_image_path)
        log.info(f"带掩膜的图片已保存到: {output_image_path}")

        return output_image_path, json_output_path

    except Exception as e:
        log.error(f"在 run_system 中发生严重错误: {e}", exc_info=True)  # 增加 exc_info
        raise e