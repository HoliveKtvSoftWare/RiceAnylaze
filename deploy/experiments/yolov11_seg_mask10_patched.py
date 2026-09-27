# -*- coding: utf-8 -*-
"""
YOLOv11-seg 高质量11类别彩色分割脚本（按341-3-processed_image.png图例配色）
修复版：解决重影问题，采用硬边缘+抗锯齿+优先级覆盖策略
本地可运行版（Windows）：路径/设备/命令行参数均已本地化

主要修复：
1. 使用阈值+形态学操作获取清晰边缘，避免过度模糊扩散
2. 重叠区域采用优先级覆盖（按置信度/面积），而非颜色混合
3. 仅在边缘1-2像素范围内做轻微羽化，实现抗锯齿而非重影
4. 颜色从RGB正确转换为OpenCV的BGR格式

本地版额外改动：
1. 原服务器绝对路径(/public/...)改为本地路径，并支持命令行覆盖
2. device 自动选择：有 CUDA 用 GPU 0，否则用 CPU
3. 图片检索去重（Windows 文件名大小写不敏感，原来 *.tif 与 *.TIF 会重复）
4. 读写图片用 imdecode/imencode，支持中文、括号等特殊字符路径
5. 增加 --limit / --only / --skip-existing，便于分批、断点续跑
6. 打印进度、耗时与统计信息

用法（在 D:\\Code\\yolov11-main-old 目录下）：
    D:\\Anaconda\\envs\\yolo\\python.exe yolov11_seg_mask10.py
    D:\\Anaconda\\envs\\yolo\\python.exe yolov11_seg_mask10.py --limit 20
    D:\\Anaconda\\envs\\yolo\\python.exe yolov11_seg_mask10.py --only 10-1,10-2,341-3
    D:\\Anaconda\\envs\\yolo\\python.exe yolov11_seg_mask10.py --images "D:\\some\\dir" --device cpu
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# =====================================================
# 让脚本优先使用本仓库自带的 ultralytics（即服务器上跑出 output_OUR-best 的那份 fork）
# 不依赖 cwd，从哪里调用都一致
# =====================================================
REPO_DIR = Path(__file__).resolve().parents[1]
if (REPO_DIR / 'ultralytics' / '__init__.py').is_file():
    sys.path.insert(0, str(REPO_DIR))


# =====================================================
# 默认路径（本地 Windows）
# =====================================================
# 原来的 /public/zhuxiaoying/chen/yolov11-main/模型文件/OUR-best.pt
MODEL_CANDIDATES = [
    str(REPO_DIR / '模型文件' / 'OUR-best.pt'),
    r'D:\Code\ultralytics-main\模型文件\OUR-best.pt',
    str(REPO_DIR / 'OUR-best.pt'),
]

# 原来的 /public/zhuxiaoying/GXU/rice_notail_data/images/test
# 本地数据是平铺目录（864 张 .tif + 864 个 .json，无 train/val/test 子目录）
DEFAULT_IMAGE_DIR = r'D:\BaiduNetdiskDownload\rice_notail_data(20260701)'

# 原来的 /public/zhuxiaoying/chen/yolov11-main/output/our_test
DEFAULT_SAVE_DIR = str(REPO_DIR / 'output' / 'our_test')

DEFAULT_EXTS = ('*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tif', '*.tiff')


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
                                 overlap_rule='confidence', edge_width=2):
    """
    无重影的mask合成：使用优先级覆盖而非颜色混合

    参数:
        masks: list of mask arrays
        classes: list of class ids
        confidences: list of confidence scores (用于优先级排序)
        colors: dict of class colors
        h, w: 输出尺寸
        overlap_rule: 'confidence'(置信度优先), 'area'(面积优先), 'order'(绘制顺序优先)
        edge_width: 边缘羽化宽度（像素）

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
        mask_aa = antialias_edge(mask_raw, edge_width=edge_width)

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
        update_mask = mask > z_buffer

        # 更新z_buffer（记录哪些像素被更高优先级的实例覆盖）
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
# 本地化辅助函数
# =====================================================
def resolve_model_path(cli_path):
    """按优先级确定模型路径"""
    candidates = ([cli_path] if cli_path else []) + MODEL_CANDIDATES
    for p in candidates:
        if p and Path(p).is_file():
            return str(Path(p).resolve())
    raise FileNotFoundError(
        "找不到模型权重 OUR-best.pt，请用 --model 指定，已尝试：\n  "
        + "\n  ".join(str(c) for c in candidates)
    )


def imread_safe(path):
    """读取图片，返回 BGR uint8；失败返回 None。兼容中文/括号路径与16位、4通道图"""
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype != np.uint8:
        # 16位等高位深图，按图像自身范围拉伸到8位
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.ndim == 3:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif img.shape[2] == 1:
            img = cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(img)


def imwrite_safe(path, img):
    """写图片，兼容中文/括号路径"""
    ext = os.path.splitext(str(path))[1] or '.png'
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(str(path))
    return True


def collect_images(image_dir, exts=DEFAULT_EXTS, recursive=False):
    """检索图片并去重（Windows 下 glob 大小写不敏感，需按绝对路径去重）"""
    root = Path(image_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"图片目录不存在: {root}")

    wanted_ext = {e.lstrip('*').lower() for e in exts}  # 含点，如 .tif
    pattern = '**/*' if recursive else '*'
    found = {}
    for entry in root.glob(pattern):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in wanted_ext:
            continue
        # 用 resolve() 归一化，避免同一文件被多次收录
        try:
            key = str(entry.resolve())
        except OSError:
            key = str(entry)
        found[key] = entry
    return sorted(found.values(), key=lambda p: p.name)


def pick_device(cli_device):
    """默认自动选设备：有 CUDA 用 GPU 0，否则 CPU"""
    if cli_device:
        return cli_device
    try:
        import torch
        return '0' if torch.cuda.is_available() else 'cpu'
    except Exception:
        return 'cpu'


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='YOLOv11-seg 11类别彩色分割（本地版）',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--model', default=None, help='模型权重路径')
    parser.add_argument('--images', default=DEFAULT_IMAGE_DIR, help='图片目录')
    parser.add_argument('--save', default=DEFAULT_SAVE_DIR, help='输出目录')
    parser.add_argument('--recursive', action='store_true', help='递归搜索子目录')
    parser.add_argument('--limit', type=int, default=0, help='只处理前 N 张（0=全部）')
    parser.add_argument('--only', default=None,
                        help='只处理指定图片名（不含扩展名），逗号分隔，如 10-1,341-3')
    parser.add_argument('--skip-existing', action='store_true',
                        help='已存在 color_mask 结果的图片跳过（断点续跑）')
    parser.add_argument('--device', default=None, help='推理设备，如 0 / cpu（默认自动）')
    parser.add_argument('--imgsz', type=int, default=640, help='推理尺寸')
    parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值')
    parser.add_argument('--iou', type=float, default=0.45, help='NMS IoU 阈值')
    parser.add_argument('--no-retina', action='store_true',
                        help='关闭 retina_masks（原脚本为 True，一般不要关）')
    parser.add_argument('--overlap-rule', default='confidence',
                        choices=['confidence', 'area', 'order'], help='重叠区域优先级规则')
    parser.add_argument('--edge-width', type=int, default=2, help='mask 边缘羽化宽度（像素）')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # ---------------- 路径 ----------------
    model_path = resolve_model_path(args.model)
    image_dir = args.images
    save_dir = Path(args.save)
    device = pick_device(args.device)

    for sub in ('color_mask', 'overlay', 'label_txt'):
        (save_dir / sub).mkdir(parents=True, exist_ok=True)

    # ---------------- 加载模型 ----------------
    from ultralytics import YOLO
    import ultralytics

    print(f"ultralytics: {ultralytics.__version__}  ({ultralytics.__file__})")
    print(f"模型: {model_path}")
    print(f"图片目录: {image_dir}")
    print(f"输出目录: {save_dir}")
    print(f"设备: {device}   imgsz={args.imgsz} conf={args.conf} iou={args.iou} "
          f"retina_masks={not args.no_retina}")

    model = YOLO(model_path)
    names = model.names

    # 打印类别映射关系（调试用）
    print("模型类别映射:")
    for idx, name in names.items():
        print(f"  {idx}: {name}")

    # ---------------- 搜索图片 ----------------
    image_files = collect_images(image_dir, recursive=args.recursive)

    if args.only:
        wanted = {s.strip().lower() for s in args.only.split(',') if s.strip()}
        image_files = [p for p in image_files if p.stem.lower() in wanted]
        missing = wanted - {p.stem.lower() for p in image_files}
        if missing:
            print("警告：以下名字在图片目录中未找到 ->", ', '.join(sorted(missing)))

    if args.limit and args.limit > 0:
        image_files = image_files[:args.limit]

    print(f"\n找到图片数量: {len(image_files)}")

    if not image_files:
        print("没有可处理的图片，检查 --images / --only 参数。")
        return 1

    # =================================================
    # 主预测
    # =================================================
    total = len(image_files)
    done = 0
    skipped = 0
    failed = []
    t_start = time.time()

    for k, img_path in enumerate(image_files, 1):

        mask_file = save_dir / 'color_mask' / (img_path.stem + '.png')

        if args.skip_existing and mask_file.exists():
            skipped += 1
            print(f"[{k}/{total}] 跳过(已存在): {img_path.name}")
            continue

        t0 = time.time()
        print(f"[{k}/{total}] 预测: {img_path.name}")

        img = imread_safe(img_path)
        if img is None:
            failed.append(img_path.name)
            print(f"  !! 无法读取，已跳过: {img_path}")
            continue

        h, w = img.shape[:2]

        results = model.predict(
            source=str(img_path),
            conf=args.conf,
            iou=args.iou,
            imgsz=args.imgsz,
            retina_masks=not args.no_retina,
            device=device,
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
                overlap_rule=args.overlap_rule,  # 置信度高的覆盖低的
                edge_width=args.edge_width
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
        imwrite_safe(mask_file, color_mask)

        # -------------------------------------------------
        # overlay图（自然混合，无重影无影子）
        # -------------------------------------------------
        # 使用mask判断是否有分割区域，仅在分割区域做overlay
        mask_any = (color_mask.sum(axis=2) > 0).astype(np.float32)
        mask_any = cv2.GaussianBlur(mask_any, (3, 3), 0)  # 轻微平滑边缘
        mask_3ch = np.stack([mask_any] * 3, axis=2)

        # 只在有mask的区域混合，保持原图其他区域不变
        overlay = (img * (1 - mask_3ch * 0.3) + color_mask * (mask_3ch * 0.3)).astype(np.uint8)

        imwrite_safe(save_dir / 'overlay' / img_path.name, overlay)

        # -------------------------------------------------
        # txt类别
        # -------------------------------------------------
        with open(
            save_dir / 'label_txt' / (img_path.stem + '.txt'),
            'w',
            encoding='utf-8'
        ) as f:
            for line in txt_lines:
                f.write(line + '\n')

        done += 1
        print(f"  完成 {img_path.name}  实例={len(txt_lines)}  {time.time() - t0:.2f}s")

    print("\n全部预测完成！")
    print(f"输出目录: {save_dir}")
    print(f"成功 {done} 张，跳过 {skipped} 张，失败 {len(failed)} 张，"
          f"总耗时 {time.time() - t_start:.1f}s")
    if failed:
        print("失败清单:")
        for name in failed:
            print("  -", name)
    return 0


if __name__ == '__main__':
    sys.exit(main())
