# -*- coding: utf-8 -*-
"""按邮箱删除一个用户及其全部数据（主要用于清理测试账号）。

为什么需要它
------------
测试账号（`README.md` 里的 `deploy_check@example.com`）只能通过
`POST /api/auth/register` 创建，**接口没有删除用户的入口**；用 psql 手工删又容易
漏掉 `analyses` / `upload_batches` 的外键与磁盘上的原图、预览、结果文件。
界面上的"删除记录"只会删记录，账号本身还在。

删除范围（先删子表再删用户，避免外键报错）：
    1. `analyses`      该用户的记录，以及这些记录在磁盘上的
                       原图 / `<名称>.preview.jpg` / 分割图 / LabelMe JSON / `_sidecar_*`
    2. `upload_batches` 该用户的批次
    3. `users`         账号本身
    4. 空目录           该用户在 `app_storage/user_data/` 与 `originals/` 下的目录

用法（后端环境）：

    :: 先看会删什么（默认干跑，不动任何数据）
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\cleanup_test_account.py --email deploy_check@example.com

    :: 确认后真删
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\cleanup_test_account.py --email deploy_check@example.com --delete
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

APP = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, APP)
os.chdir(APP)

from sqlmodel import Session, create_engine, select              # noqa: E402
from app.core.config import settings                              # noqa: E402
from app.models.analysis import Analysis                          # noqa: E402
from app.models.batch import UploadBatch                          # noqa: E402
from app.models.user import UserTable                             # noqa: E402
from app.services.image_preview import preview_path_for           # noqa: E402

_SIDECAR_PREFIX = '_sidecar_'


def _files_of(record):
    """一条记录在磁盘上的文件（含自动生成的预览）。"""
    paths = [record.original_file_path, record.annotated_image_path,
             record.result_json_path, record.excel_report_path]
    if record.original_file_path:
        paths.append(preview_path_for(record.original_file_path))
    return [p for p in paths if p]


def _sidecar_files(record):
    """记录输出目录里的旁路中间文件（在输出目录内枚举，路径不存在数据库里）。"""
    out = []
    for p in (record.annotated_image_path, record.result_json_path):
        if not p:
            continue
        d = os.path.dirname(p)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith(_SIDECAR_PREFIX):
                out.append(os.path.join(d, name))
    return out


def main():
    ap = argparse.ArgumentParser(description='删除指定邮箱的用户及其全部数据')
    ap.add_argument('--email', required=True, help='要删除的账号邮箱')
    ap.add_argument('--delete', action='store_true', help='真的删除（默认只干跑）')
    ap.add_argument('--keep-files', action='store_true',
                    help='只删数据库记录与账号，保留磁盘文件')
    ap.add_argument('--keep-user', action='store_true',
                    help='只删该账号的分析记录（含文件）与批次，保留账号本身——'
                         '适用于清理"文件早已丢失、列表里只剩余占位提示"的死记录')
    args = ap.parse_args()

    email = args.email.strip().lower()
    engine = create_engine(settings.DATABASE_URL.replace('+asyncpg', ''), echo=False)

    with Session(engine) as s:
        user = s.exec(select(UserTable).where(UserTable.email == email)).first()
        if not user:
            print(f'[未找到] 邮箱 {email} 不存在，无事可做')
            return 0

        rows = s.exec(select(Analysis).where(Analysis.user_id == user.id)).all()
        batches = s.exec(select(UploadBatch).where(UploadBatch.user_id == user.id)).all()

        print(f'账号: {email}  (id={user.id}, role={user.role}, active={user.is_active})')
        print(f'  分析记录 {len(rows)} 条，批次 {len(batches)} 个')

        files = []
        for r in rows:
            files += _files_of(r)
            files += _sidecar_files(r)
        files = sorted(set(os.path.normpath(p) for p in files))
        existing = [p for p in files if os.path.exists(p)]
        print(f'  磁盘文件 {len(existing)} 个'
              + ('（--keep-files，将保留）' if args.keep_files else ''))

        user_dirs = [os.path.join(settings.STORAGE_PATH, str(user.id)),
                     os.path.join(settings.STORAGE_PATH, 'originals', str(user.id))]
        for d in user_dirs:
            if os.path.isdir(d):
                n = sum(len(f) for _r, _d, f in os.walk(d))
                print(f'  目录 {d}（{n} 个文件）')

        if not args.delete:
            print('\n（干跑，未改动任何数据；确认后加 --delete 执行）')
            return 0

        if not args.keep_files:
            removed = failed = 0
            for p in existing:
                try:
                    os.remove(p)
                    removed += 1
                except OSError as e:
                    failed += 1
                    print(f'  [删除失败] {p}: {e}')
            print(f'  已删除文件 {removed} 个，失败 {failed} 个')

        for r in rows:
            s.delete(r)
        for b in batches:
            s.delete(b)
        if args.keep_user:
            s.commit()
            print(f'  已删除数据库记录：analyses {len(rows)}，upload_batches {len(batches)}；'
                  f'账号保留（--keep-user）')
            print('\n完成。')
            return 0

        s.delete(user)
        s.commit()
        print(f'  已删除数据库记录：analyses {len(rows)}，upload_batches {len(batches)}，users 1')

    if not args.keep_files and not args.keep_user:
        for d in user_dirs:
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
                print(f'  已移除目录 {d}'
                      + ('' if not os.path.isdir(d) else '（仍非空，请手工检查）'))

    print('\n完成。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
