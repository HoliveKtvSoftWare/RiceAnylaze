# -*- coding: utf-8 -*-
"""端到端验证：refine 检测头集成后，各任务的 sidecar / 原生通道是否正常。

用法（必须用后端环境，因为它要 import app.*）：
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\verify_refine_tasks.py            # 全部
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\verify_refine_tasks.py leaf_our   # 指定
"""
import json
import os
import sys
import time

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
WORKSPACE = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

from app.core.tasks import get_task, get_tasks                     # noqa: E402
from app.services.analysis_service import _run_via_sidecar          # noqa: E402
from app.services.yolo_inference import run_system                  # noqa: E402

IMAGE = os.path.join(WORKSPACE, 'test', '10-1.tif')
OUT_ROOT = os.path.join(BACKEND_DIR, '_seg_out', 'sidecar_check')

FORK_KEYS = ['leaf_our', 'leaf_v11_head', 'leaf_v11_p2_head',
             'leaf_asf', 'leaf_svbdet', 'leaf_sod', 'leaf_subtle']
NATIVE_KEYS = ['leaf', 'leaf_v11']


def polygon_area(points):
    """鞋带公式（labelme 的 points 是 [[x, y], ...]）"""
    s = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def summarize(json_path):
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    areas = {}
    for sh in data.get('shapes', []):
        areas[sh['label']] = areas.get(sh['label'], 0.0) + polygon_area(sh['points'])
    total = sum(areas.values())
    return data.get('shapes', []), areas, total


def main(argv):
    keys = argv[1:] or (FORK_KEYS + NATIVE_KEYS)
    tasks = get_tasks()
    os.makedirs(OUT_ROOT, exist_ok=True)
    ok_all = True

    for key in keys:
        if key not in tasks:
            print(f'{key:18s} 跳过（未注册）')
            continue
        task = tasks[key]
        out_dir = os.path.join(OUT_ROOT, key)
        os.makedirs(out_dir, exist_ok=True)
        t0 = time.time()
        try:
            if task.runtime == 'fork':
                ann, js = _run_via_sidecar(task, IMAGE, out_dir, 'check')
                meta = {}
                p = os.path.join(out_dir, f'_sidecar_{key}.json')
                if os.path.exists(p):
                    with open(p, encoding='utf-8') as f:
                        meta = json.load(f)
                extra = f"ultralytics={meta.get('ultralytics')} runtime={os.path.basename(str(meta.get('runtime')))} mask_refine={meta.get('mask_refine')}"
            else:
                ann, js = run_system(
                    model_path=task.model_path, image_path=IMAGE, output_path=out_dir,
                    output_basename='check', smooth=task.smooth,
                    smooth_exclude=task.smooth_exclude, embed_image=task.embed_image,
                    colors=task.colors, draw_first=task.draw_first,
                    outline_labels=task.outline_labels, imgsz=task.predict_imgsz,
                    conf=task.conf, iou=task.iou, retina_masks=task.retina_masks,
                    preview_smooth=task.preview_smooth,
                    preserve_mask_topology=task.preserve_mask_topology,
                    validate_side_bundles=task.validate_side_bundles)
                extra = 'native(8.3.27)'
            shapes, areas, total = summarize(js)
            print(f'✅ {key:18s} [{task.runtime:6s}] {len(shapes):4d} shapes  面积和={total/1e6:8.2f} Mpx  '
                  f'{time.time()-t0:5.1f}s  {extra}')
            for lab in sorted(areas, key=lambda k: -areas[k]):
                print(f'      {lab:14s} {areas[lab]/1e6:8.2f} Mpx')
        except Exception as e:                                   # noqa: BLE001
            ok_all = False
            print(f'❌ {key:18s} [{task.runtime:6s}] 失败: {type(e).__name__}: {e}')

    print('\n结果:', '全部通过' if ok_all else '存在失败项')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
