# -*- coding: utf-8 -*-
"""构建「带 mask_refine 的推理运行时」—— 项目自有的 ultralytics 副本。

为什么需要
----------
`OUR-best.pt` / `exp12` / `exp61` 三个剑叶权重是用**带 Mask Refinement Block 的
检测头**训练的，权重里存着 4 个 `mask_refine.*` 张量：

    model.29.mask_refine.0.weight/bias, model.29.mask_refine.2.weight/bias

而通用 ultralytics（8.3.27 / 8.4.23 等任何官方发行版）的 `Segment` 头都没有这个
模块，加载时这 4 个张量会被**静默丢弃**，refinement 完全不参与推理 —— 表现为掩膜
整体偏胖、小维管束（*_small / *_big）被吃掉，实测掩膜覆盖率 0.35 vs 正确值 0.20。

本脚本把用户那份带 refinement 的头装进一份项目自有的 ultralytics 副本：

    .ultra_refine/ultralytics/              内核 = 旧项目 fork(8.4.23，含 nn/Addmodules)
      nn/modules/head.py                    = deploy/runtime/heads/head_mask_refine.py + 代次垫片
      models/yolo/segment/predict.py        打补丁：兼容经典代次头的 proto 返回结构

装完以后 `.ultra_refine` 自包含，运行时不再依赖 D:\\Code\\yolov11-main-old。

用法：
    python deploy/runtime/build_refine_ultralytics.py            # 构建/重建
    python deploy/runtime/build_refine_ultralytics.py --check    # 只检查现状，不重建
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
WORKSPACE = os.path.dirname(BACKEND_DIR)
DST_ROOT = os.path.join(BACKEND_DIR, '.ultra_refine')        # 产物（项目自有，勿手工改）
DST_PKG = os.path.join(DST_ROOT, 'ultralytics')
SRC_PKG = r'D:\Code\yolov11-main-old\ultralytics'             # 内核来源（仅构建时需要）
HEAD_SRC = os.path.join(BACKEND_DIR, 'deploy', 'runtime', 'heads', 'head_mask_refine.py')  # 头（项目内保存）

PYTHON = r'D:\Anaconda\envs\yolo\python.exe'

# head_mask_refine.py 的期望指纹（防止误改）
HEAD_MD5 = '578396A9D94145E2086DF1288967D178'

ALIAS_SHIM = '''

# ===== 代次垫片（由 deploy/runtime/build_refine_ultralytics.py 追加，勿手工删除）=====
# 本文件是 8.3 代次的头（带 mask_refine），而本运行时内核是 8.4.23；
# 内核的 nn/modules/__init__.py 与 nn/tasks.py 会 import 四个 YOLO26 变体，
# 本文件没有它们，这里别名到基类。项目内所有权重都不含 YOLO26 结构
# （已逐个扫描：无 one2one / Segment26），因此不影响任何任务。
Segment26 = Segment
OBB26 = OBB
Pose26 = Pose
YOLOESegment26 = YOLOESegment
__all__ = (*__all__, "Segment26", "OBB26", "Pose26", "YOLOESegment26")
'''

OLD_PROTO_LINE = '        protos = preds[0][1] if isinstance(preds[0], tuple) else preds[1]'
NEW_PROTO_LINE = '''        # 兼容经典代次(8.3 系)分割头：返回 (det, (feats, mc, proto))，proto 在最后一项
        if isinstance(preds[0], tuple):
            protos = preds[0][1]
        elif isinstance(preds[1], (list, tuple)) and len(preds[1]) == 3:
            protos = preds[1][-1]
        else:
            protos = preds[1]'''

# 兼容执行：不含 mask_refine 的权重（对比方法 / exp08 / exp59）反序列化后没有该子模块，
# 直接调用会 AttributeError；有权重的（OUR-best/exp12/exp61）反序列化时会带上 mask_refine。
OLD_REFINE_CALL = '        p = self.mask_refine(p)'
NEW_REFINE_CALL = '''        if hasattr(self, "mask_refine"):  # 权重里有 refinement 才执行（由 build 脚本加的保护）
            p = self.mask_refine(p)'''

PREDICT_PY = os.path.join(DST_PKG, 'models', 'yolo', 'segment', 'predict.py')


def md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest().upper()


def log(msg):
    print(msg, flush=True)


def build():
    if not os.path.isdir(SRC_PKG):
        raise SystemExit(f'内核来源不存在: {SRC_PKG}')
    if not os.path.isfile(HEAD_SRC):
        raise SystemExit(f'头文件不存在: {HEAD_SRC}')
    if md5(HEAD_SRC) != HEAD_MD5:
        log(f'!! 警告: {HEAD_SRC} 指纹与记录不符（期望 {HEAD_MD5}，实际 {md5(HEAD_SRC)}），请确认改动是有意的')

    log(f'[1/4] 复制内核 {SRC_PKG} -> {DST_PKG}')
    if os.path.isdir(DST_ROOT):
        shutil.rmtree(DST_ROOT)
    shutil.copytree(SRC_PKG, DST_PKG,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

    log('[2/4] 安装带 mask_refine 的头')
    dst_head = os.path.join(DST_PKG, 'nn', 'modules', 'head.py')
    shutil.copyfile(HEAD_SRC, dst_head)
    with open(dst_head, encoding='utf-8') as f:
        head_text = f.read()
    n = head_text.count(OLD_REFINE_CALL)
    if n != 1:
        raise SystemExit(f'!! 头文件里 "p = self.mask_refine(p)" 出现 {n} 次，预期 1 次，请人工确认')
    head_text = head_text.replace(OLD_REFINE_CALL, NEW_REFINE_CALL, 1)
    with open(dst_head, 'w', encoding='utf-8') as f:
        f.write(head_text + ALIAS_SHIM)

    log('[3/4] 给预测器打「经典代次 proto 兼容」补丁')
    with open(PREDICT_PY, encoding='utf-8') as f:
        text = f.read()
    if OLD_PROTO_LINE not in text:
        if '兼容经典代次(8.3 系)分割头' in text:
            log('      补丁已存在，跳过')
        else:
            raise SystemExit(f'!! 未在 {PREDICT_PY} 找到目标行，内核版本可能变了，请人工确认')
    else:
        text = text.replace(OLD_PROTO_LINE, NEW_PROTO_LINE, 1)
        with open(PREDICT_PY, 'w', encoding='utf-8') as f:
            f.write(text)

    log('[4/4] 自检')
    code = (
        'import sys; sys.path.insert(0, r"%s");'
        'import ultralytics, inspect;'
        'from ultralytics.nn.modules import head as H;'
        'from ultralytics.nn.modules.head import Segment, Segment26, OBB26, Pose26, YOLOESegment26;'
        'src = inspect.getsource(Segment.__init__);'
        'print("ultralytics", ultralytics.__version__, ultralytics.__file__);'
        'print("mask_refine 生效:", "mask_refine" in src);'
        'print("YOLO26 垫片:", Segment26 is Segment, OBB26 is H.OBB)'
    ) % DST_ROOT
    proc = subprocess.run([PYTHON, '-c', code], capture_output=True, text=True, encoding='utf-8')
    log(proc.stdout.strip() or proc.stderr.strip())
    if proc.returncode != 0:
        raise SystemExit('!! 自检失败')
    if 'mask_refine 生效: True' not in proc.stdout:
        raise SystemExit('!! mask_refine 未生效，请检查头文件')
    log(f'完成: {DST_ROOT}')


def check():
    dst_head = os.path.join(DST_PKG, 'nn', 'modules', 'head.py')
    for p in (DST_PKG, dst_head, PREDICT_PY):
        log(f'{"存在" if os.path.exists(p) else "缺失"}  {p}')
    if os.path.isfile(dst_head):
        with open(dst_head, encoding='utf-8') as f:
            t = f.read()
        log(f'  head.py: mask_refine={"mask_refine" in t}  代次垫片={"代次垫片" in t}')
    if os.path.isfile(PREDICT_PY):
        with open(PREDICT_PY, encoding='utf-8') as f:
            t = f.read()
        log(f'  predict.py: 经典代次兼容补丁={"兼容经典代次" in t}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只检查现状')
    a = ap.parse_args()
    check() if a.check else build()
