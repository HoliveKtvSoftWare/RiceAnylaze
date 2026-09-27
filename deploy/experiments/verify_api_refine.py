# -*- coding: utf-8 -*-
"""HTTP 端到端验证：登录 -> 任务列表 -> 上传 -> 轮询 -> 检查 sidecar 运行时/检测头

用法（用后端环境）：
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\verify_api_refine.py [task_key] [图片]
默认 leaf_our + test\\10-1.tif
"""
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

BASE = 'http://127.0.0.1:8000'
EMAIL = 'deploy_check@example.com'
PWD = 'Rice@2026test'
TASK = sys.argv[1] if len(sys.argv) > 1 else 'leaf_our'
BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKSPACE = BACKEND_DIR.parent
IMAGE = sys.argv[2] if len(sys.argv) > 2 else str(WORKSPACE / 'test' / '10-1.tif')
STORAGE = str(BACKEND_DIR / 'app_storage' / 'user_data')

s = requests.Session()
r = s.post(f'{BASE}/api/auth/jwt/login', data={'username': EMAIL, 'password': PWD}, timeout=30)
r.raise_for_status()
H = {'Authorization': f"Bearer {r.json()['access_token']}"}
print('登录成功')

tasks = s.get(f'{BASE}/api/analysis/tasks', headers=H, timeout=30).json()
items = tasks.get('tasks', tasks) if isinstance(tasks, dict) else tasks
print(f'任务数: {len(items)}')

with open(IMAGE, 'rb') as f:
    r = s.post(f'{BASE}/api/analysis/upload', headers=H,
               files={'file': (os.path.basename(IMAGE), f, 'image/tiff')},
               data={'task_type': TASK}, timeout=600)
r.raise_for_status()
up = r.json()
aid = up.get('analysis_id') or up.get('analysisId')
print(f"已提交: {up.get('analysis_id') or up.get('analysisId')}  ({up.get('message')})")

rec = None
for i in range(100):
    time.sleep(3)
    rows = s.get(f'{BASE}/api/analysis/history', headers=H, params={'task_type': TASK}, timeout=60).json()
    rows = rows.get('analyses', rows) if isinstance(rows, dict) else rows
    for row in rows:
        if str(row.get('analysis_id') or row.get('analysisId')) == str(aid):
            rec = row
            break
    if rec and str(rec.get('status')) in ('completed', 'failed', 'error'):
        break
    print(f'  等待中… {i*3}s')

if not rec:
    print('未找到记录'); sys.exit(1)
print('状态:', rec.get('status'))

orig = rec.get('originalFilename') or rec.get('original_filename') or ''
stem = os.path.splitext(orig)[0]
url = rec.get('annotatedImageUrl') or rec.get('annotated_image_url') or ''
parts = urlparse(url).path.split('/')            # /static/<user>/<stem>/<file>.jpg
user = parts[2] if len(parts) > 3 else ''
out_dir = os.path.join(STORAGE, user, stem)
print('输出目录:', out_dir)
if os.path.isdir(out_dir):
    for name in sorted(os.listdir(out_dir)):
        print('   ', name)
    for cand in (f'_sidecar_{TASK}.json', f'_sidecar_{TASK}.log'):
        p = os.path.join(out_dir, cand)
        if os.path.exists(p):
            print(f'--- {cand} ---')
            print(open(p, encoding='utf-8', errors='replace').read()[:800])
print('OK' if rec.get('status') == 'completed' else 'FAILED')
