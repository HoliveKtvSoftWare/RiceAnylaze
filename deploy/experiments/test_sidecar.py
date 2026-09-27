# -*- coding: utf-8 -*-
"""端到端测试旁路推理：由后端侧生成任务参数，交给 yolo 环境的子进程执行。

用后端环境（fastapi）运行本脚本即可。
"""
import json
import os
import subprocess
import sys
import time

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)
os.environ.setdefault('YOLO_CONFIG_DIR', os.path.join(BACKEND_DIR, '.ultralytics'))

from app.core.config import settings
from app.core.tasks import get_task

TASK = sys.argv[1] if len(sys.argv) > 1 else 'leaf_sod'
IMAGE = sys.argv[2] if len(sys.argv) > 2 else r'D:\Code\data_out_excel\测试数据\10-1.tif'
OUT = os.path.join(BACKEND_DIR, '_seg_out', 'sidecar_test', TASK)
os.makedirs(OUT, exist_ok=True)

task = get_task(TASK)
spec_path = os.path.join(OUT, 'spec.json')
result_json = os.path.join(OUT, 'result.json')
log_path = os.path.join(OUT, 'sidecar.log')
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
json.dump(spec, open(spec_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

cmd = [settings.FORK_PYTHON, settings.SIDECAR_SCRIPT,
       '--spec', spec_path, '--image', IMAGE, '--out-dir', OUT,
       '--basename', 'sidecar_' + TASK, '--result-json', result_json]
env = os.environ.copy()
env['PYTHONPATH'] = settings.FORK_PYLIBS + os.pathsep + env.get('PYTHONPATH', '')
env['PYTHONIOENCODING'] = 'utf-8'

print('任务:', task.key, task.name, '| 权重:', os.path.basename(task.model_path))
print('解释器:', settings.FORK_PYTHON)
t0 = time.time()
with open(log_path, 'w', encoding='utf-8') as logf:
    proc = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env, timeout=3600)
print('子进程退出码:', proc.returncode, ' 耗时 %.1fs' % (time.time() - t0))

if os.path.exists(result_json):
    data = json.load(open(result_json, encoding='utf-8'))
    print('结果:', json.dumps(data, ensure_ascii=False)[:300])
    for k in ('annotated_image_path', 'result_json_path'):
        p = data.get(k)
        if p:
            print('  %s: %s (%s)' % (k, os.path.basename(p),
                                     ('%.0f KB' % (os.path.getsize(p) / 1024)) if os.path.exists(p) else '不存在'))
    if data.get('ok'):
        d = json.load(open(data['result_json_path'], encoding='utf-8'))
        print('  LabelMe shapes =', len(d['shapes']))
else:
    print('未生成 result.json')
print('\n日志末尾:')
print(''.join(open(log_path, encoding='utf-8').readlines()[-6:]))
