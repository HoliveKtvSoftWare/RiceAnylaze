# -*- coding: utf-8 -*-
"""把 9 个剑叶模型在同一张图上的分割结果拼成一张对比图。

原生模型（后端环境可加载）直接调用 run_system；
对比方法（依赖旧 fork）复用 deploy/sidecar_infer.py 的子进程方式。

用法（后端环境）：
    python deploy/make_model_comparison.py [图片路径]
"""
import json
import os
import subprocess
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)
os.environ.setdefault('YOLO_CONFIG_DIR', os.path.join(BACKEND_DIR, '.ultralytics'))

from app.core.config import settings
from app.features.task_catalog.catalog import get_task, get_tasks
from app.infrastructure.inference.runner import run_system

IMAGE = sys.argv[1] if len(sys.argv) > 1 else r'D:\Code\data_out_excel\测试数据\10-1.tif'
OUT = os.path.join(BACKEND_DIR, '_seg_out', 'model_compare')
os.makedirs(OUT, exist_ok=True)

ORDER = ['leaf', 'leaf_v11', 'leaf_v11_head', 'leaf_v11_p2_head', 'leaf_our',
         'leaf_asf', 'leaf_svbdet', 'leaf_sod', 'leaf_subtle']
ORDER = [k for k in ORDER if k in get_tasks()]

panels = []
for key in ORDER:
    task = get_task(key)
    out_dir = os.path.join(OUT, key)
    os.makedirs(out_dir, exist_ok=True)
    print(f'>>> {key} ({task.runtime}) {task.name}')
    try:
        if task.runtime == 'fork':
            spec_path = os.path.join(out_dir, 'spec.json')
            result_json = os.path.join(out_dir, 'result.json')
            log_path = os.path.join(out_dir, 'sidecar.log')
            spec = {
                'key': task.key, 'name': task.name, 'model_path': task.model_path,
                'colors': {k: list(v) for k, v in task.colors.items()},
                'draw_first': list(task.draw_first), 'outline_labels': list(task.outline_labels),
                'smooth': task.smooth, 'smooth_exclude': list(task.smooth_exclude),
                'preview_smooth': task.preview_smooth,
                'preserve_mask_topology': task.preserve_mask_topology,
                'validate_side_bundles': task.validate_side_bundles,
                'embed_image': task.embed_image, 'predict_imgsz': task.predict_imgsz,
                'conf': task.conf, 'iou': task.iou, 'retina_masks': task.retina_masks,
            }
            json.dump(spec, open(spec_path, 'w', encoding='utf-8'), ensure_ascii=False)
            env = os.environ.copy()
            env['PYTHONPATH'] = settings.FORK_PYLIBS + os.pathsep + env.get('PYTHONPATH', '')
            env['PYTHONIOENCODING'] = 'utf-8'
            cmd = [settings.FORK_PYTHON, settings.SIDECAR_SCRIPT, '--spec', spec_path,
                   '--image', IMAGE, '--out-dir', out_dir, '--basename', key,
                   '--result-json', result_json]
            with open(log_path, 'w', encoding='utf-8') as lf:
                subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env, timeout=3600)
            data = json.load(open(result_json, encoding='utf-8'))
            if not data.get('ok'):
                raise RuntimeError(data.get('error'))
            img_path = data['annotated_image_path']
        else:
            img_path, _ = run_system(
                model_path=task.model_path, image_path=IMAGE, output_path=out_dir,
                output_basename=key, smooth=task.smooth, smooth_exclude=task.smooth_exclude,
                embed_image=task.embed_image, colors=task.colors, draw_first=task.draw_first,
                outline_labels=task.outline_labels, imgsz=task.predict_imgsz,
                conf=task.conf, iou=task.iou, retina_masks=task.retina_masks,
                preview_smooth=task.preview_smooth,
                preserve_mask_topology=task.preserve_mask_topology,
                validate_side_bundles=task.validate_side_bundles)
        panels.append((task.name, img_path))
        print('    完成:', os.path.basename(img_path))
    except Exception as e:                                    # noqa: BLE001
        print('    失败:', str(e)[:120])

if not panels:
    print('没有任何结果')
    sys.exit(1)

# 拼图：3 列
COLS, W, TH = 3, 700, 46
try:
    from PIL import Image, ImageDraw, ImageFont
    FONT = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 30)
except Exception:
    from PIL import Image, ImageDraw, ImageFont
    FONT = ImageFont.load_default()

ims = []
for name, p in panels:
    im = Image.open(p).convert('RGB')
    im = im.resize((W, int(im.height * W / im.width)), Image.LANCZOS)
    ims.append((name, im))
rows = (len(ims) + COLS - 1) // COLS
rh = max(i.height for _, i in ims) + TH
canvas = Image.new('RGB', (W * COLS, rh * rows), 'white')
d = ImageDraw.Draw(canvas)
for idx, (name, im) in enumerate(ims):
    x, y = (idx % COLS) * W, (idx // COLS) * rh
    canvas.paste(im, (x, y + TH))
    d.rectangle([x, y, x + W - 1, y + TH - 1], fill=(238, 238, 238))
    d.text((x + 10, y + 8), name, fill=(0, 0, 0), font=FONT)
out_png = os.path.join(OUT, '模型对比_' + os.path.splitext(os.path.basename(IMAGE))[0] + '.png')
canvas.save(out_png)
print('\n对比图:', out_png, canvas.size)
