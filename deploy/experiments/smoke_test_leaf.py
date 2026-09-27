#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
剑叶分析（task_type=leaf）端到端测试 + 茎秆回归测试。

链路：本脚本 -> 前端服务器(5173) -> /api 反向代理 -> FastAPI(8000) -> PostgreSQL(5432)
      -> YOLO 推理 -> /static 静态图 -> Excel 导出

用法：
    python RiceAnylaze/deploy/smoke_test_leaf.py [剑叶图片] [茎秆图片]
默认：
    剑叶图 D:\\Code\\data_out_excel\\测试数据\\10-1.tif
    茎秆图 D:\\Code\\python\\yolo_program\\水稻数据集\\21c-02.png
"""
import base64
import io
import json
import os
import sys
import time

import requests

BASE = os.environ.get('BASE_URL', 'http://127.0.0.1:5173').rstrip('/')
EMAIL = os.environ.get('TEST_EMAIL', 'deploy_check@example.com')
PASSWORD = os.environ.get('TEST_PASSWORD', 'Rice@2026test')

LEAF_IMAGE = sys.argv[1] if len(sys.argv) > 1 else r'D:\Code\data_out_excel\测试数据\10-1.tif'
STEM_IMAGE = sys.argv[2] if len(sys.argv) > 2 else r'D:\Code\python\yolo_program\水稻数据集\21c-02.png'

results = []


def check(label, ok, extra=''):
    results.append(bool(ok))
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}  {extra}")
    return ok


s = requests.Session()

# ---------- 登录 ----------
s.post(BASE + '/api/auth/register', json={'email': EMAIL, 'password': PASSWORD}, timeout=30)
r = s.post(BASE + '/api/auth/jwt/login', data={'username': EMAIL, 'password': PASSWORD}, timeout=30)
token = r.json().get('access_token') if r.status_code == 200 else None
if not check('登录', bool(token), f'HTTP {r.status_code}'):
    sys.exit(1)
H = {'Authorization': f'Bearer {token}'}

# ---------- 任务列表 ----------
r = s.get(BASE + '/api/analysis/tasks', headers=H, timeout=30)
tasks = r.json().get('tasks', []) if r.status_code == 200 else []
keys = [t.get('key') for t in tasks]
check('任务列表含 stem 与 leaf', r.status_code == 200 and 'stem' in keys and 'leaf' in keys, str(tasks))

# ---------- 列定义 ----------
cols_leaf = s.get(BASE + '/api/excel/columns', params={'task_type': 'leaf'}, headers=H, timeout=30).json().get('available_columns', {})
cols_stem = s.get(BASE + '/api/excel/columns', params={'task_type': 'stem'}, headers=H, timeout=30).json().get('available_columns', {})
check('剑叶列定义（35 列）', len(cols_leaf) == 35, f"{len(cols_leaf)} 列")
check('茎秆列定义（16 列，未变）', len(cols_stem) == 16, f"{len(cols_stem)} 列")


def upload_and_wait(image, task_type, timeout=600):
    with open(image, 'rb') as fh:
        files = {'file': (os.path.basename(image), fh, 'application/octet-stream')}
        r = s.post(BASE + '/api/analysis/upload', headers=H, files=files,
                   data={'task_type': task_type}, timeout=600)
    if r.status_code != 200:
        check(f'上传 {task_type}', False, f'HTTP {r.status_code} {r.text[:150]}')
        return None
    aid = r.json().get('analysis_id')
    check(f'上传 {task_type}', bool(aid), f"analysis_id={aid} task_type={r.json().get('task_type')}")

    record = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        rr = s.get(BASE + '/api/analysis/history', params={'task_type': task_type}, headers=H, timeout=60)
        for rec in rr.json():
            if rec['analysisId'] == aid:
                record = rec
        if record and record['status'] in ('completed', 'failed'):
            break
        time.sleep(4)
    check(f'{task_type} 推理完成', bool(record) and record['status'] == 'completed',
          (record or {}).get('status', 'timeout'))
    if record:
        check(f'{task_type} 记录类型正确', record.get('taskType') == task_type, record.get('taskType'))
    return record


def export_excel(analysis_id, task_type, columns):
    body = {'selectedColumns': columns, 'unit': 'um', 'taskType': task_type}
    r = s.post(BASE + f'/api/excel/{analysis_id}', headers=H, json=body, timeout=300)
    if r.status_code != 200:
        check(f'{task_type} Excel 导出', False, f'HTTP {r.status_code} {r.text[:200]}')
        return None
    data = r.json()
    check(f'{task_type} Excel 导出', bool(data.get('content')), data.get('filename', ''))
    return data


# ---------- 剑叶 ----------
print('\n===== 剑叶分析（leaf）=====')
leaf_rec = upload_and_wait(LEAF_IMAGE, 'leaf')
if leaf_rec:
    img = s.get(leaf_rec['annotatedImageUrl'], timeout=120)
    check('剑叶标注图可访问', img.status_code == 200 and len(img.content) > 1000,
          f"{img.status_code} {len(img.content) // 1024}KB")

    data = export_excel(leaf_rec['analysisId'], 'leaf', list(cols_leaf.keys()))
    if data:
        try:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(base64.b64decode(data['content'])))
            print('\n--- 剑叶指标（单位 um/um2）---')
            for k, v in df.iloc[0].items():
                print(f'    {k}: {v}')
            check('剑叶 Excel 列数一致', len(df.columns) == len(cols_leaf), f'{len(df.columns)} 列')
            check('剑叶关键指标非零',
                  float(df.iloc[0].get('主脉面积', 0) or 0) > 0
                  and float(df.iloc[0].get('侧脉1面积', 0) or 0) > 0
                  and int(df.iloc[0].get('侧脉1大维管束数目', 0) or 0) > 0,
                  '主脉/侧脉1 面积与维管束数目')
            check('比例尺自动识别（≈1.4837 um/px）',
                  abs(float(df.iloc[0].get('比例尺(µm/px)', 0) or 0) - 1.4837) < 0.01,
                  str(df.iloc[0].get('比例尺(µm/px)')))
        except Exception as e:
            check('剑叶 Excel 解析', False, repr(e))

# ---------- 茎秆回归 ----------
print('\n===== 茎秆分析回归（stem）=====')
stem_rec = upload_and_wait(STEM_IMAGE, 'stem')
if stem_rec:
    data = export_excel(stem_rec['analysisId'], 'stem',
                        ['filename', 'largeTailCount', 'smallTailCount', 'stemArea', 'cavityArea'])
    if data:
        try:
            import pandas as pd
            df = pd.read_excel(io.BytesIO(base64.b64decode(data['content'])))
            print('\n--- 茎秆指标（回归）---')
            for k, v in df.iloc[0].items():
                print(f'    {k}: {v}')
            check('茎秆回归：维管束数目与面积可用',
                  int(df.iloc[0].get('大维管束数目', 0) or 0) > 0
                  and float(df.iloc[0].get('茎秆面积', 0) or 0) > 0,
                  '大维管束数目 > 0 且 茎秆面积 > 0')
        except Exception as e:
            check('茎秆 Excel 解析', False, repr(e))

# ---------- 混合类型批量导出应被拒绝 ----------
if leaf_rec and stem_rec:
    r = s.post(BASE + '/api/excel/batch', headers=H,
               json={'analysisIds': [leaf_rec['analysisId'], stem_rec['analysisId']],
                     'selectedColumns': ['filename'],
                     'taskType': 'leaf'}, timeout=120)
    check('混合类型批量导出被拒绝(400)', r.status_code == 400, f"HTTP {r.status_code} {r.text[:110]}")

print(f'\n===== 结果: {sum(results)}/{len(results)} 项通过 =====')
sys.exit(0 if all(results) else 2)
