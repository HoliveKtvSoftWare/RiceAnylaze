# -*- coding: utf-8 -*-
"""为历史记录补齐"原图预览图"（.tif -> .preview.jpg）。

新上传的图片由后端在保存时自动生成预览；本脚本用于给**功能上线前**已存在的
历史记录补上一份，之后历史界面的"原始图片"才能正常显示。

用法（后端环境）：
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\backfill_previews.py [--force]
"""
import argparse
import os
import sys
import time
from pathlib import Path

APP = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, APP)
os.chdir(APP)

from sqlmodel import Session, create_engine, select          # noqa: E402
from app.core.config import settings                          # noqa: E402
from app.models.analysis import Analysis                      # noqa: E402
from app.services.image_preview import ensure_preview, preview_path_for  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='已存在的预览也重新生成')
    args = ap.parse_args()

    engine = create_engine(settings.DATABASE_URL.replace('+asyncpg', ''), echo=False)
    with Session(engine) as s:
        rows = s.exec(select(Analysis)).all()

    print(f'数据库中共 {len(rows)} 条分析记录')
    made = reused = skipped = failed = 0
    t0 = time.time()
    for r in rows:
        p = r.original_file_path
        if not p or not os.path.exists(p):
            skipped += 1
            print(f'  跳过(原图不存在) {r.analysis_id} {p}')
            continue
        out = preview_path_for(p)
        existed = os.path.exists(out)
        got = ensure_preview(p, force=args.force)
        if not got:
            failed += 1
            print(f'  失败 {r.analysis_id} {os.path.basename(p)}')
        elif existed and not args.force:
            reused += 1
        else:
            made += 1
            print(f'  生成 {os.path.basename(got)} ({os.path.getsize(got)/1024:.0f} KB)')

    print(f'\n完成：新生成 {made}，已存在 {reused}，跳过 {skipped}，失败 {failed}，'
          f'耗时 {time.time()-t0:.1f}s')


if __name__ == '__main__':
    main()
