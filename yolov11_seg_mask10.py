# -*- coding: utf-8 -*-
"""
YOLOv11-seg 高质量11类别彩色分割脚本（按341-3-processed_image.png图例配色）
修复版：解决重影问题，采用硬边缘+抗锯齿+优先级覆盖策略

主要修复：
1. 使用阈值+形态学操作获取清晰边缘，避免过度模糊扩散
2. 重叠区域采用优先级覆盖（按置信度/面积），而非颜色混合
3. 仅在边缘1-2像素范围内做轻微羽化，实现抗锯齿而非重影
4. 颜色从RGB正确转换为OpenCV的BGR格式
"""

from ultralytics import YOLO
import os
from pathlib import Path
import cv2
import numpy as np

# =====================================================
# 路径
# =====================================================
model_path = '/public/zhuxiaoying/GXU/ultralytics-main/runs/train/exp086/weights/best.pt'
image_dir  = '/public/zhuxiaoying/GXU/rice_notail_data/images/test'
save_dir   = '/public/zhuxiaoying/GXU/yolov11-main/runs/segment_10_test'

os.makedirs(save_dir, exist_ok=True)
os.makedirs(save_dir + '/color_mask', exist_ok=True)
os.makedirs(save_dir + '/overlay', exist_ok=True)
os.makedirs(save_dir + '/label_txt', exist_ok=True)

# =====================================================
# 加载模型
# =====================================================
model = YOLO(model_path)
names = model.names

# 打印类别映射关系（调试用）
print("模型类别映射:")
for idx, name in names.items():
    print(f"  {idx}: {name}")

# =====================================================
# 根据341-3-processed_image.png图例定义颜色（BGR格式）
# 图例RGB值 → OpenCV BGR值
# =====================================================
CLASS_COLORS = {
    0:  (0,   0,   128),    # body1       - 深红 RGB(128,0,0)
    1:  (128, 0,   0),      # body1_small - 深蓝 RGB(0,0,128)
    2:  (0,   128, 0),       # body2       - 绿色 RGB(0,128,0)
    3:  (128, 0,   128),     # body2_small - 紫红 RGB(128,0,128)
    4:  (0,   128, 128),     # body1_big   - 橄榄 RGB(128,128,0)
    5:  (128, 128, 0),       # side1       - 青色 RGB(0,128,128)
    6:  (0,   128, 64),      # side1_big   - 深绿 RGB(64,128,0)
    7:  (0,   0,   64),      # side1_small - 暗红 RGB(64,0,0)
    8:  (128, 128, 128),     # side2       - 灰色 RGB(128,128,128)
    9:  (0,   128, 192),     # side2_big   - 橙色 RGB(192,128,0)
    10: (0,   0,   192),     # side2_small - 红色 RGB(192,0,0)
}

# =====================================================
# 核心修复：抗锯齿边缘处理（无重影）
# =====================================================
def antialias_edge(mask, edge_width=2):
    """
    仅对mask边缘做轻微羽化，保持内部完全 opaque，避免重影
    
    参数:
        mask: 原始mask (H, W), 值域 [0, 1] 或 [0, 255]
        edge_width: 边缘羽化宽度（像素），默认2px
    
    返回:
        mask_aa: 抗锯齿后的mask，内部为1，边缘渐变到0
    """
    # 确保二值化
    mask_bin = (mask > 0.5).astype(np.uint8)
    
    # 如果mask为空，直接返回
    if mask_bin.sum() == 0:
        return mask.astype(np.float32)
    
    # 形态学膨胀获取外轮廓区域
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (edge_width*2+1, edge_width*2+1))
    mask_dilated = cv2.dilate(mask_bin, kernel, iterations=1)
    
    # 形态学腐蚀获取内核心区域
    mask_eroded = cv2.erode(mask_bin, kernel, iterations=1)
    
    # 边缘区域 = 膨胀 - 腐蚀
    edge_region = mask_dilated - mask_eroded
    
    # 原始mask转为float
    mask_float = mask_bin.astype(np.float32)
    
    # 对原始mask做轻微高斯模糊（仅用于边缘计算）
    mask_blur = cv2.GaussianBlur(mask_float, (0, 0), sigmaX=1.0)
    mask_blur = np.clip(mask_blur, 0, 1)
    
    # 构建最终mask：核心区域保持1.0，边缘区域使用模糊值，外部为0
    mask_aa = mask_float.copy()
    
    # 仅在边缘区域应用羽化
    edge_coords = edge_region > 0
    mask_aa[edge_coords] = mask_blur[edge_coords]
    
    return mask_aa


def composite_masks_no_ghosting(masks, classes, confidences, colors, h, w, 
                                 overlap_rule='confidence'):
    """
    无重影的mask合成：使用优先级覆盖而非颜色混合
    
    参数:
        masks: list of mask arrays
        classes: list of class ids
        confidences: list of confidence scores (用于优先级排序)
        colors: dict of class colors
        h, w: 输出尺寸
        overlap_rule: 'confidence'(置信度优先), 'area'(面积优先), 'order'(绘制顺序优先)
    
    返回:
        color_mask: (H, W, 3) 合成后的彩色mask
    """
    # 初始化
    color_mask = np.zeros((h, w, 3), dtype=np.uint8)
    z_buffer = np.zeros((h, w), dtype=np.float32)  # 深度/优先级缓冲
    
    # 准备实例信息并按优先级排序
    instances = []
    for i in range(len(masks)):
        cls_id = int(classes[i])
        conf = float(confidences[i]) if i < len(confidences) else 1.0
        
        # resize mask
        mask_raw = cv2.resize(masks[i], (w, h), interpolation=cv2.INTER_LINEAR)
        
        # 抗锯齿处理（关键修复：边缘羽化而非整体模糊）
        mask_aa = antialias_edge(mask_raw, edge_width=2)
        
        # 计算面积作为备选优先级
        area = mask_aa.sum()
        
        instances.append({
            'idx': i,
            'cls_id': cls_id,
            'color': np.array(colors[cls_id], dtype=np.uint8),
            'mask': mask_aa,
            'conf': conf,
            'area': area
        })
    
    # 按优先级排序（优先级高的后绘制，覆盖前面的）
    if overlap_rule == 'confidence':
        # 置信度高的覆盖置信度低的
        instances.sort(key=lambda x: x['conf'])
    elif overlap_rule == 'area':
        # 面积大的覆盖面积小的（或反过来，根据需求）
        instances.sort(key=lambda x: x['area'])
    else:
        # 保持原始顺序（YOLO默认通常是置信度排序）
        pass
    
    # 逐个实例绘制，使用覆盖而非混合
    for inst in instances:
        mask = inst['mask']
        color = inst['color']
        
        # 创建该实例的彩色图
        inst_color = np.zeros((h, w, 3), dtype=np.uint8)
        for c in range(3):
            inst_color[:, :, c] = (mask * color[c]).astype(np.uint8)
        
        # 使用mask作为alpha，直接覆盖（无颜色混合）
        # 只有当前mask值 > z_buffer的地方才绘制（处理同一像素多次覆盖）
        mask_bin = (mask > 0.5).astype(np.uint8)
        
        # 更新z_buffer（记录哪些像素被更高优先级的实例覆盖）
        update_mask = mask > z_buffer
        z_buffer = np.maximum(z_buffer, mask)
        
        # 仅在update_mask为True的位置更新颜色
        for c in range(3):
            color_mask[:, :, c] = np.where(
                update_mask, 
                inst_color[:, :, c], 
                color_mask[:, :, c]
            )
    
    return color_mask


# =====================================================
# 搜索图片
# =====================================================
exts = ['*.jpg','*.jpeg','*.png','*.bmp','*.tif']
image_files = []

for e in exts:
    image_files.extend(Path(image_dir).glob(e))
    image_files.extend(Path(image_dir).glob(e.upper()))

image_files = sorted(image_files)

print("\n找到图片数量:", len(image_files))

# =====================================================
# 主预测
# =====================================================
for img_path in image_files:

    print("预测:", img_path.name)

    img = cv2.imread(str(img_path))
    h, w = img.shape[:2]

    results = model.predict(
        source=str(img_path),
        conf=0.25,
        iou=0.45,
        imgsz=640,
        retina_masks=True,
        device='0',
        verbose=False
    )

    r = results[0]

    # 初始化
    txt_lines = []

    if r.masks is not None:

        masks = r.masks.data.cpu().numpy()
        classes = r.boxes.cls.cpu().numpy().astype(int)
        confidences = r.boxes.conf.cpu().numpy() if hasattr(r.boxes, 'conf') else np.ones(len(classes))

        # 使用无重影合成方法
        color_mask = composite_masks_no_ghosting(
            masks=masks,
            classes=classes,
            confidences=confidences,
            colors=CLASS_COLORS,
            h=h,
            w=w,
            overlap_rule='confidence'  # 置信度高的覆盖低的
        )

        # 生成标签文本
        for i in range(len(classes)):
            cls_id = int(classes[i])
            txt_lines.append(f"{cls_id} {names[cls_id]}")

    else:
        # 无检测结果时创建空白mask
        color_mask = np.zeros((h, w, 3), dtype=np.uint8)

    # -------------------------------------------------
    # 保存彩色mask（无重影）
    # -------------------------------------------------
    cv2.imwrite(
        os.path.join(save_dir, 'color_mask', img_path.stem + '.png'),
        color_mask
    )

    # -------------------------------------------------
    # overlay图（自然混合，无重影无影子）
    # -------------------------------------------------
    # 使用mask判断是否有分割区域，仅在分割区域做overlay
    mask_any = (color_mask.sum(axis=2) > 0).astype(np.float32)
    mask_any = cv2.GaussianBlur(mask_any, (3, 3), 0)  # 轻微平滑边缘
    mask_3ch = np.stack([mask_any] * 3, axis=2)
    
    # 只在有mask的区域混合，保持原图其他区域不变
    overlay = (img * (1 - mask_3ch * 0.3) + color_mask * (mask_3ch * 0.3)).astype(np.uint8)

    cv2.imwrite(
        os.path.join(save_dir, 'overlay', img_path.name),
        overlay
    )

    # -------------------------------------------------
    # txt类别
    # -------------------------------------------------
    with open(
        os.path.join(save_dir, 'label_txt', img_path.stem + '.txt'),
        'w',
        encoding='utf-8'
    ) as f:
        for line in txt_lines:
            f.write(line + '\n')

print("\n全部预测完成！")
print(save_dir)