#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
剑叶多个权重横向评估（imgsz=640，与训练分辨率一致）。

用法：
    python deploy/experiments/eval_leaf_models.py [imgsz] [图片数]

评估内容：
  1. 逐标签贪心匹配 IoU（与人工标注对比）
  2. 侧脉 side1/side2 的交叉匹配 —— 用于判断模型是否只是把两条侧脉的命名搞反了
  3. 总面积比（预测/GT）
"""
import io
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

IMGSZ = int(sys.argv[1]) if len(sys.argv) > 1 else 640
N_IMG = int(sys.argv[2]) if len(sys.argv) > 2 else 3

DATA = r'D:\Code\data_out_excel\测试数据'
MODELS = [
    ('OUR-best.pt(v12,P2)', r'D:\Code\ultralytics-main\模型文件\OUR-best.pt'),
    ('v11-best(exp08)', r'D:\Code\ultralytics-main\模型文件\yolov11_best(exp08).pt'),
    ('v11-head(exp12)', r'D:\Code\ultralytics-main\模型文件\yolov11_head_best(exp12).pt'),
    ('v11-p2(exp59)', r'D:\Code\ultralytics-main\模型文件\yolov11_p2_best(exp59).pt'),
    ('v11-p2-head(exp61)', r'D:\Code\ultralytics-main\模型文件\yolov11_p2_head_best(exp61).pt'),
]
LABELS = ['body1', 'side1', 'side2', 'body2', 'body_big', 'body1_small',
          'body2_small', 'side1_big', 'side1_small', 'side2_big', 'side2_small']
REGIONS = ['body1', 'side1', 'side2', 'body2']

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
os.environ.setdefault('YOLO_CONFIG_DIR', os.path.join(BACKEND_DIR, '.ultralytics'))


def raster(points, box):
    x0, y0, x1, y1 = box
    w, h = max(1, int(np.ceil(x1 - x0))), max(1, int(np.ceil(y1 - y0)))
    im = Image.new('1', (w, h), 0)
    ImageDraw.Draw(im).polygon([(float(x - x0), float(y - y0)) for x, y in points], fill=1)
    return np.array(im, dtype=bool)


def bbox(points):
    x = [p[0] for p in points]; y = [p[1] for p in points]
    return min(x), min(y), max(x) + 1, max(y) + 1


def iou_pair(pa, pb, ba=None, bb=None):
    if pa is None or pb is None or len(pa) < 3 or len(pb) < 3:
        return 0.0
    ba = ba or bbox(pa); bb = bb or bbox(pb)
    # 包围盒不相交直接返回 0（加速）
    if ba[2] <= bb[0] or bb[2] <= ba[0] or ba[3] <= bb[1] or bb[3] <= ba[1]:
        return 0.0
    box = (min(ba[0], bb[0]), min(ba[1], bb[1]), max(ba[2], bb[2]), max(ba[3], bb[3]))
    ma, mb = raster(pa, box), raster(pb, box)
    inter = np.logical_and(ma, mb).sum()
    union = np.logical_or(ma, mb).sum()
    return (inter / union) if union else 0.0


def poly_area(points):
    x = np.array([p[0] for p in points], dtype=np.float64)
    y = np.array([p[1] for p in points], dtype=np.float64)
    return abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0


def load_gt(path):
    with io.open(path, encoding='utf-8') as f:
        d = json.load(f)
    out = {}
    for sh in d.get('shapes', []):
        lbl = sh.get('label')
        if lbl in LABELS and sh.get('shape_type') == 'polygon' and len(sh.get('points', [])) >= 3:
            p = np.array(sh['points'], dtype=np.float64)
            out.setdefault(lbl, []).append((p, bbox(p), poly_area(p)))
    return out


def match_stats(gts, preds):
    """贪心匹配，返回 (匹配数, 平均IoU, GT面积, 预测面积)"""
    pairs = []
    for gi, (gp, gb, ga) in enumerate(gts):
        for pi, (pp, pb, pa) in enumerate(preds):
            v = iou_pair(gp, pp, gb, pb)
            if v > 0.1:
                pairs.append((v, gi, pi))
    pairs.sort(reverse=True)
    ug, up, matched = set(), set(), []
    for v, gi, pi in pairs:
        if gi in ug or pi in up:
            continue
        ug.add(gi); up.add(pi); matched.append(v)
    return len(matched), (float(np.mean(matched)) if matched else 0.0), \
        sum(g[2] for g in gts), sum(p[2] for p in preds)


images = [os.path.join(DATA, f'{n}.tif') for n in ('10-1', '10-2', '10-3')][:N_IMG]
gts = {os.path.basename(i): load_gt(os.path.join(DATA, os.path.splitext(os.path.basename(i))[0] + '.json')) for i in images}

from ultralytics import YOLO

print(f'imgsz={IMGSZ}  图片={[os.path.basename(i) for i in images]}\n')
rows = []
for name, path in MODELS:
    model = YOLO(path)
    per_label = {l: [] for l in LABELS}
    cross_side = []          # side1/side2 交叉匹配 IoU
    total_gt = total_match = 0
    t0 = time.time()
    for img in images:
        res = model(img, imgsz=IMGSZ, retina_masks=True, verbose=False)[0]
        names = res.names
        preds = {}
        for i, c in enumerate(res.boxes.cls):
            lbl = names[int(c)]
            poly = np.asarray(res.masks.xy[i], dtype=np.float64)
            if lbl in LABELS and len(poly) >= 3:
                preds.setdefault(lbl, []).append((poly, bbox(poly), poly_area(poly)))
        gt = gts[os.path.basename(img)]
        for lbl in LABELS:
            if lbl not in gt:
                continue
            m, iou, ag, ap = match_stats(gt[lbl], preds.get(lbl, []))
            per_label[lbl].append((len(gt[lbl]), len(preds.get(lbl, [])), m, iou, ap / ag if ag else 0))
            total_gt += len(gt[lbl]); total_match += m
        # 交叉：预测 side1 与 GT side2
        for a, b in (('side1', 'side2'), ('side2', 'side1')):
            if a in preds and b in gt:
                m, iou, ag, ap = match_stats(gt[b], preds[a])
                cross_side.append(iou)
    dt = time.time() - t0
    mean_iou = float(np.mean([v[3] for l in LABELS for v in per_label[l]])) if any(per_label.values()) else 0
    mean_iou_region = float(np.mean([v[3] for l in REGIONS for v in per_label[l]])) if any(per_label[l] for l in REGIONS) else 0
    mean_iou_bundle = float(np.mean([v[3] for l in LABELS if l not in REGIONS for v in per_label[l]]))
    rows.append((name, mean_iou, mean_iou_region, mean_iou_bundle, total_match / total_gt if total_gt else 0,
                 float(np.mean(cross_side)) if cross_side else 0, dt))
    print(f'--- {name} ---')
    print(f'{"标签":<14}{"GT":>4}{"预测":>6}{"匹配":>6}{"IoU":>8}{"面积比":>8}')
    for lbl in LABELS:
        if not per_label[lbl]:
            continue
        gt_n = sum(v[0] for v in per_label[lbl]); pd_n = sum(v[1] for v in per_label[lbl])
        mt = sum(v[2] for v in per_label[lbl]); iou = np.mean([v[3] for v in per_label[lbl]])
        ar = np.mean([v[4] for v in per_label[lbl]])
        print(f'{lbl:<14}{gt_n:>4}{pd_n:>6}{mt:>6}{iou:>8.3f}{ar:>8.2f}')
    print()

print('===== 汇总（3 张图平均）=====')
print(f'{"模型":<22}{"总IoU":>8}{"区域IoU":>9}{"维管束IoU":>11}{"匹配率":>8}{"侧脉交叉IoU":>13}')
for name, mi, mr, mb, mr2, cs, dt in rows:
    print(f'{name:<22}{mi:>8.3f}{mr:>9.3f}{mb:>11.3f}{mr2:>8.2f}{cs:>13.3f}')
print('\n说明：匹配率 = 匹配上的实例数 / GT 实例数；“侧脉交叉IoU”= 预测 side1 与 GT side2 的匹配 IoU，'
      '若该值明显高于同标签 IoU，说明模型只是把两条侧脉的命名搞反了。')
