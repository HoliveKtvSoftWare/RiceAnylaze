#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Rice_system 部署后的端到端冒烟测试。

链路：本脚本 -> 前端服务器(5173) -> /api 反向代理 -> FastAPI(8000) -> PostgreSQL(5432) -> YOLO 推理 -> /static 静态图

用法：
    python RiceAnylaze/deploy/experiments/smoke_test.py [测试图片路径]
环境变量：
    BASE_URL   默认 http://127.0.0.1:5173
    TEST_EMAIL / TEST_PASSWORD  测试账号（会尝试注册，已存在则直接登录）
"""
import os
import sys
import time

import requests

BASE = os.environ.get('BASE_URL', 'http://127.0.0.1:5173').rstrip('/')
EMAIL = os.environ.get('TEST_EMAIL', 'deploy_check@example.com')
PASSWORD = os.environ.get('TEST_PASSWORD', 'Rice@2026test')
IMAGE = sys.argv[1] if len(sys.argv) > 1 else None

s = requests.Session()
results = []


def check(label, ok, extra=''):
    results.append(bool(ok))
    print(f"[{'OK  ' if ok else 'FAIL'}] {label}  {extra}")
    return ok


print(f'== 目标: {BASE} ==')

# 1. 前端页面
try:
    r = s.get(BASE + '/', timeout=20)
    check('前端首页 /', r.status_code == 200 and 'id="app"' in r.text, f'HTTP {r.status_code}')
except Exception as e:
    check('前端首页 /', False, repr(e))

# 2. SPA history 回退
try:
    r = s.get(BASE + '/login', timeout=20)
    check('SPA 路由 /login', r.status_code == 200 and 'id="app"' in r.text, f'HTTP {r.status_code}')
except Exception as e:
    check('SPA 路由 /login', False, repr(e))

# 3. 反向代理到后端（未登录应 401）
try:
    r = s.get(BASE + '/api/analysis/history', timeout=20)
    check('代理 /api -> FastAPI', r.status_code == 401, f'HTTP {r.status_code}')
except Exception as e:
    check('代理 /api -> FastAPI', False, repr(e))

# 4. 注册（已存在时 fastapi-users 返回 400，视为可用）
try:
    r = s.post(BASE + '/api/auth/register', json={'email': EMAIL, 'password': PASSWORD}, timeout=30)
    check('注册账号', r.status_code in (200, 201, 400), f'HTTP {r.status_code} {r.text[:100]}')
except Exception as e:
    check('注册账号', False, repr(e))

# 5. 登录
token = None
try:
    r = s.post(BASE + '/api/auth/jwt/login', data={'username': EMAIL, 'password': PASSWORD}, timeout=30)
    token = r.json().get('access_token') if r.status_code == 200 else None
    check('登录获取 JWT', bool(token), f'HTTP {r.status_code} {r.text[:100]}')
except Exception as e:
    check('登录获取 JWT', False, repr(e))

if not token:
    print('\n== 登录失败，后续步骤跳过 ==')
    sys.exit(1)

H = {'Authorization': f'Bearer {token}'}

# 6. 当前用户
try:
    r = s.get(BASE + '/api/users/me', headers=H, timeout=20)
    check('/api/users/me', r.status_code == 200, f'HTTP {r.status_code} {r.text[:120]}')
except Exception as e:
    check('/api/users/me', False, repr(e))

analysis_id = None
if IMAGE:
    # 7. 上传图片（走代理，测试完整链路）
    try:
        with open(IMAGE, 'rb') as fh:
            files = {'file': (os.path.basename(IMAGE), fh, 'image/png')}
            r = s.post(BASE + '/api/analysis/upload', headers=H, files=files, timeout=300)
        ok = r.status_code == 200
        analysis_id = r.json().get('analysis_id') if ok else None
        check('上传图片并提交后台任务', ok, f'HTTP {r.status_code} {r.text[:160]}')
    except Exception as e:
        check('上传图片并提交后台任务', False, repr(e))

    # 8. 轮询推理结果
    record = None
    if analysis_id:
        deadline = time.time() + 600
        while time.time() < deadline:
            try:
                r = s.get(BASE + '/api/analysis/history', headers=H, timeout=60)
                for rec in r.json():
                    if rec['analysisId'] == analysis_id:
                        record = rec
            except Exception as e:
                print(f'      轮询异常: {e!r}')
            if record and record['status'] in ('completed', 'failed'):
                break
            time.sleep(5)
        check(
            'YOLO 推理完成',
            bool(record) and record['status'] == 'completed',
            (record or {}).get('status', 'timeout'),
        )

    # 9. 标注图 / JSON（同源 /static 地址）
    if record and record.get('annotatedImageUrl'):
        try:
            r = s.get(record['annotatedImageUrl'], timeout=120)
            check('标注图 /static 可访问', r.status_code == 200 and len(r.content) > 1000,
                  f'HTTP {r.status_code} {len(r.content)}B {record["annotatedImageUrl"]}')
        except Exception as e:
            check('标注图 /static 可访问', False, repr(e))
    if record and record.get('resultJsonUrl'):
        try:
            r = s.get(record['resultJsonUrl'], timeout=120)
            shapes = len(r.json().get('shapes', [])) if r.status_code == 200 else -1
            check('LabelMe JSON 可访问', r.status_code == 200 and shapes > 0,
                  f'HTTP {r.status_code} shapes={shapes}')
        except Exception as e:
            check('LabelMe JSON 可访问', False, repr(e))

print(f'\n== 结果: {sum(results)}/{len(results)} 项通过 ==')
sys.exit(0 if all(results) else 2)
