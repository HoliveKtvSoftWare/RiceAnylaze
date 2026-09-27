# -*- coding: utf-8 -*-
"""原图预览：把浏览器无法直接渲染的上传原图（.tif/.tiff 等）转成可直接 <img> 显示的 JPEG。

背景
----
系统允许上传科研常用的 `.tif` 切片，但**浏览器不支持 TIFF**，所以历史记录里的
"原始图片"一直显示不出来（原来是直接把原图 URL 丢给 `<img>`）。

做法
----
为每个上传原图生成一份**同目录、同名**的 `<去扩展名>.preview.jpg`
（长边 <= 1600、质量 85），历史接口优先返回它的 URL，原图 URL 仍然保留
（`originalFileUrl`）供下载。预览图放在静态目录内，无需新增路由或鉴权。

旧记录（本功能上线前上传的）可用 `RiceAnylaze/deploy/backfill_previews.py` 批量补齐；
此外历史接口还带一层**按需兜底**（`ensure_preview_cached`）：预览缺失时现场补一张，
所以"删了预览但原图还在"的记录下次打开历史就会自动恢复，不再长期显示占位提示。
兜底带失败负缓存，避免前端 2 秒一次的轮询反复解码同一张坏图。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

log = logging.getLogger(__name__)

PREVIEW_SUFFIX = '.preview.jpg'   # 例：xxx_10-1.tif -> xxx_10-1.preview.jpg
MAX_SIDE = 1600                   # 预览图长边上限（够看清全貌，又不至于太大）
JPEG_QUALITY = 85

# 生成失败的原图 -> (尝试时刻, 原图 mtime)：一段时间内不再重试，防止轮询时反复解码。
# 原图被替换（mtime 变化）后自动允许重试。
_FAILED_RETRY_SECONDS = 600.0
_FAILED_CACHE_MAX = 1000
_failed: Dict[str, Tuple[float, float]] = {}


def preview_path_for(original_path: str) -> str:
    """约定的预览图路径：与原图同目录、去掉原扩展名后加 .preview.jpg"""
    root, _ = os.path.splitext(original_path)
    return root + PREVIEW_SUFFIX


def preview_is_fresh(original_path: str) -> bool:
    """预览已存在且不旧于原图时返回 True（此时无需读盘解码）。"""
    try:
        out = preview_path_for(original_path)
        return (os.path.exists(out)
                and os.path.getmtime(out) >= os.path.getmtime(original_path))
    except OSError:
        return False


def _recently_failed(original_path: str) -> bool:
    """该原图最近生成失败过、且文件没变过，则跳过重试。"""
    entry = _failed.get(original_path)
    if not entry:
        return False
    tried_at, tried_mtime = entry
    try:
        mtime = os.path.getmtime(original_path)
    except OSError:
        return True                      # 原图读不到了，等缓存过期再说
    if mtime != tried_mtime:
        _failed.pop(original_path, None)  # 原图被换过，允许重试
        return False
    return (time.time() - tried_at) < _FAILED_RETRY_SECONDS


def ensure_preview_cached(original_path: str,
                          max_side: int = MAX_SIDE) -> Optional[str]:
    """历史接口用的按需兜底：缺失就补一张，失败/解码不了则短期不再重试。

    预览已是最新时只做一次 stat（不重复解码大 tif），因此可以在列表请求里安全调用。
    """
    if not original_path or not os.path.exists(original_path):
        return None
    if preview_is_fresh(original_path):
        return preview_path_for(original_path)
    if _recently_failed(original_path):
        return None

    got = ensure_preview(original_path, max_side=max_side)
    if got:
        _failed.pop(original_path, None)
        return got

    try:
        mtime = os.path.getmtime(original_path)
    except OSError:
        mtime = 0.0
    if len(_failed) >= _FAILED_CACHE_MAX:
        _failed.clear()
    _failed[original_path] = (time.time(), mtime)
    return None


def imread_any(path: str) -> Optional[np.ndarray]:
    """读取任意格式图片为 BGR uint8；兼容中文/括号路径、16 位、灰度、4 通道"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.dtype != np.uint8:
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.ndim == 3:
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        elif img.shape[2] == 1:
            img = cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
    return np.ascontiguousarray(img)


def ensure_preview(original_path: str, force: bool = False,
                   max_side: int = MAX_SIDE) -> Optional[str]:
    """确保存在可显示的 JPEG 预览图，返回其路径；失败返回 None（调用方回退到原图 URL）。

    已存在且比原图新时直接复用（不重复解码 20MB 的 tif）。
    """
    if not original_path or not os.path.exists(original_path):
        return None

    out = preview_path_for(original_path)
    if not force and preview_is_fresh(original_path):
        return out

    try:
        img = imread_any(original_path)
        if img is None:
            log.warning('无法解码原图，跳过预览生成: %s', original_path)
            return None
        h, w = img.shape[:2]
        scale = min(1.0, float(max_side) / float(max(h, w)))
        if scale < 1.0:
            img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                             interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            log.warning('JPEG 编码失败: %s', original_path)
            return None
        buf.tofile(out)
        log.info('已生成原图预览: %s (%dx%d) -> %s', original_path, w, h, out)
        return out
    except Exception as e:                                            # noqa: BLE001
        log.error('生成原图预览失败 %s: %s', original_path, e)
        return None


SCALE_BAR_UM = 500.0


def detect_scale_um_per_px(image_path: Optional[str]) -> Optional[float]:
    """
    从图像右下象限的比例尺自动推算像素当量（µm/px）。

    做法与参考实现一致：在右下象限找纯红(>=240,<=20,<=20)/纯蓝(<=20,<=20,>=240)
    像素，取"单行红+蓝像素数"的最大值 s 作为比例尺线条长度，
    则 k = SCALE_BAR_UM / s。

    返回 None 表示未识别到比例尺（调用方应回退到请求里的 scale 参数）。
    """
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        import numpy as np
        from PIL import Image

        with Image.open(image_path) as im:
            arr = np.array(im.convert("RGB"))
        if arr.ndim != 3 or arr.shape[2] < 3:
            return None
        h, w = arr.shape[:2]
        q = arr[h // 2:, w // 2:, :3].astype(np.int16)
        red = (q[:, :, 0] >= 240) & (q[:, :, 1] <= 20) & (q[:, :, 2] <= 20)
        blue = (q[:, :, 0] <= 20) & (q[:, :, 1] <= 20) & (q[:, :, 2] >= 240)
        rows = red.sum(axis=1) + blue.sum(axis=1)
        if rows.size == 0:
            return None
        s = int(rows.max())
        if s <= 0:
            return None
        return SCALE_BAR_UM / s
    except Exception as e:
        log.warning(f"自动识别比例尺失败（将回退到请求参数）: {e}")
        return None
