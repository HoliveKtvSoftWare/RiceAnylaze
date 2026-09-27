# -*- coding: utf-8 -*-
"""清理孤儿预览图 / 残留旁路文件。

背景
----
原图预览 `<名称>.preview.jpg` 的路径**不在数据库里**，只能由 `original_file_path`
推导。此前 `POST /api/analysis/delete/batch` 漏了这一步，删掉记录后预览图被留在
静态目录中成为孤儿（`app_storage/user_data/originals/` 下那些只剩 `.preview.jpg`、
原图已消失的文件就是这么来的）。2026-09-17 已修接口，但**修复前产生的残留不会自动消失**，
用本脚本清理。

本脚本默认**只清理预览图**；`_sidecar_*.log/.json` 是当前结果的推理凭证
（里面记着 `mask_refine=True` 这类自检信息），只有对应记录已被删除时才可用
`--include-sidecar` 一并清掉。

只删静态目录里的文件，**不动数据库、不动有记录的原图与结果**。

用法（后端环境，必须先停后端或等其空闲，避免误删正在生成的预览）：

    :: 先看会删什么（默认就是干跑，不删任何东西）
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\cleanup_previews.py

    :: 确认无误后真删
    D:\\Anaconda\\envs\\fastapi\\python.exe deploy\\cleanup_previews.py --delete
"""
import argparse
import os
import re
import sys
import time
from pathlib import Path

APP = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, APP)
os.chdir(APP)

from sqlmodel import Session, create_engine, select              # noqa: E402
from app.core.config import settings                              # noqa: E402
from app.models.analysis import Analysis                          # noqa: E402
from app.services.image_preview import PREVIEW_SUFFIX             # noqa: E402

# 上传记录的文件名形如 <uuid>_<原名>_<时间戳>.<ext>；预处理结果形如 <uuid>_<原名>.<ext>
_UUID_PREFIX = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}'
                          r'-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}_')
_UUID_ONLY = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}'
                        r'-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_SIDECAR_NAME = re.compile(r'^_sidecar_.+\.(log|json)$')
_ORIGINAL_EXTS = ('.tif', '.tiff', '.png', '.jpg', '.jpeg', '.bmp')


def _norm(path):
    """统一成可比对的绝对路径（数据库里存的是 ./app_storage/... 这类相对路径）。"""
    try:
        return os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError):
        return None


def collect_db_paths(app_dir):
    """返回 (被引用的文件路径集合, 分析记录列表)。"""
    referenced = set()
    engine = create_engine(settings.DATABASE_URL.replace('+asyncpg', ''), echo=False)
    with Session(engine) as s:
        rows = s.exec(select(Analysis)).all()
    for r in rows:
        for p in (r.original_file_path, r.annotated_image_path,
                  r.result_json_path, r.excel_report_path):
            n = _norm(p) if p else None
            if n:
                referenced.add(n)
    return referenced, rows


def record_output_dirs(rows):
    """所有"仍存在"的分析记录对应的目录（绝对路径）。

    旁路中间文件 `_sidecar_*.log/.json` 写在原图所在目录里：目录还在记录名下，
    说明这些日志是**当前结果**的推理凭证，不能当垃圾删掉。
    """
    dirs = set()
    for r in rows:
        for p in (r.original_file_path, r.annotated_image_path, r.result_json_path):
            if not p:
                continue
            for candidate in (os.path.dirname(p), p):
                n = _norm(candidate)
                if n:
                    dirs.add(n)
    return dirs


def _original_variants(stem):
    """预览文件名去掉 .preview.jpg 后的 stem 对应的候选原图路径（同名不同扩展名）。"""
    return [stem + ext for ext in _ORIGINAL_EXTS]


def _classify(stem, original_exists, still_recorded):
    """给孤儿预览分类，仅用于报告。"""
    if still_recorded:
        # 原图仍被记录引用，说明是"记录还在、预览却被删过"的异常残留（历史接口会自动重建）
        return 'record-exists'
    if original_exists:
        return 'record-missing-original-present'
    if _UUID_PREFIX.match(os.path.basename(stem)):
        return 'processed-output'
    return 'uploaded-original-gone'


LABELS = {
    'record-exists': '原图仍被记录引用（异常残留，历史接口会自动重建）',
    'record-missing-original-present': '原图还在但记录已删',
    'processed-output': '分析输出目录里的预览（记录已删）',
    'uploaded-original-gone': '原图与记录都已不存在',
    'sidecar-temp': '旁路推理残留的中间文件（记录已删）',
}


def find_orphans(storage_root, referenced, record_dirs, min_age_seconds,
                 include_sidecar=False):
    """遍历静态目录，返回 (path, size, kind)；跳过刚生成的文件。"""
    orphans = []
    now = time.time()
    for dirpath, _dirnames, filenames in os.walk(storage_root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                if now - os.path.getmtime(path) < min_age_seconds:
                    continue                     # 刚生成/正在生成，跳过
                size = os.path.getsize(path)
            except OSError:
                continue

            if name.endswith(PREVIEW_SUFFIX):
                stem = path[:-len(PREVIEW_SUFFIX)]
                variants = _original_variants(stem)
                still_recorded = any(_norm(v) in referenced for v in variants)
                if still_recorded:
                    continue                     # 记录仍在，预览是需要的
                orphans.append((path, size,
                                _classify(stem, any(os.path.exists(v) for v in variants),
                                          still_recorded)))
            elif include_sidecar and _SIDECAR_NAME.match(name):
                # 旁路中间文件是**当前结果**的推理凭证（含 mask_refine 自检行），
                # 只有对应记录已被删除时才算垃圾；默认不动，需要时加 --include-sidecar。
                if _norm(dirpath) in record_dirs:
                    continue
                orphans.append((path, size, 'sidecar-temp'))
    return orphans


def main():
    ap = argparse.ArgumentParser(description='清理孤儿预览图与残留旁路中间文件')
    ap.add_argument('--delete', action='store_true', help='真的删除（默认只干跑列清单）')
    ap.add_argument('--min-age-minutes', type=float, default=10.0,
                    help='跳过最近 N 分钟内改动的文件，避免误删正在生成的预览（默认 10）')
    ap.add_argument('--storage', default=settings.STORAGE_PATH,
                    help=f'静态目录（默认 {settings.STORAGE_PATH}）')
    ap.add_argument('--include-sidecar', action='store_true',
                    help='同时清理"记录已删除"的 _sidecar_*.log/.json（默认保留）')
    args = ap.parse_args()

    storage_root = args.storage
    if not os.path.isdir(storage_root):
        print(f'[错误] 静态目录不存在: {storage_root}')
        return 1

    referenced, rows = collect_db_paths(APP)
    record_dirs = record_output_dirs(rows)
    print(f'数据库分析记录 {len(rows)} 条，引用文件 {len(referenced)} 个，'
          f'有效输出目录 {len(record_dirs)} 个')
    print(f'扫描目录 {os.path.abspath(storage_root)}'
          f'（跳过最近 {args.min_age_minutes:g} 分钟内改动的文件）\n')

    orphans = find_orphans(storage_root, referenced, record_dirs,
                           args.min_age_minutes * 60, args.include_sidecar)
    orphans.sort(key=lambda x: x[2])

    total = 0
    kind_now = None
    for path, size, kind in orphans:
        if kind != kind_now:
            kind_now = kind
            print(f'--- {kind}: {LABELS.get(kind, kind)} ---')
        total += size
        print(f'  {size/1024:9.1f} KB  {os.path.relpath(path, storage_root)}')

    print(f'\n共 {len(orphans)} 个孤儿文件，合计 {total/1024/1024:.2f} MB')
    if not orphans:
        return 0

    if not args.delete:
        print('\n（干跑，未删除任何文件；确认后加 --delete 执行）')
        return 0

    deleted = failed = 0
    freed = 0
    for path, size, _kind in orphans:
        try:
            os.remove(path)
            deleted += 1
            freed += size
        except OSError as e:
            failed += 1
            print(f'  [失败] {path}: {e}')
    print(f'\n已删除 {deleted} 个（释放 {freed/1024/1024:.2f} MB），失败 {failed} 个')
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
