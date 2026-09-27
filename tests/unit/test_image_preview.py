"""`app/services/image_preview.py` 的按需兜底与负缓存回归测试。

覆盖历史接口新增的"预览缺失即现场补一张"行为，以及失败负缓存
（避免前端 2 秒一次的轮询反复解码同一张坏图）。
"""
import os
import shutil
import unittest

import cv2
import numpy as np

from app.services.image_preview import (
    PREVIEW_SUFFIX,
    _failed,
    ensure_preview_cached,
    preview_is_fresh,
    preview_path_for,
)

# 临时目录放在工作区内：受限环境下系统 TEMP 可能不可写
TEST_TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp")


def _write_png(path, size=(64, 48)):
    """写一张真实可解码的小图（PNG 用于测试，预览链路行为与 tif 一致）。"""
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:, :, 1] = 180
    cv2.imwrite(path, img)


class EnsurePreviewCachedTests(unittest.TestCase):
    def setUp(self):
        _failed.clear()
        os.makedirs(TEST_TMP_ROOT, exist_ok=True)
        self.tmp = os.path.join(TEST_TMP_ROOT, self._testMethodName)
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.original = os.path.join(self.tmp, "10-1.png")
        _write_png(self.original)

    def test_generates_preview_when_missing(self):
        out = preview_path_for(self.original)
        self.assertFalse(os.path.exists(out))

        got = ensure_preview_cached(self.original)

        self.assertEqual(got, out)
        self.assertTrue(os.path.exists(out))
        self.assertTrue(preview_is_fresh(self.original))

    def test_reuses_existing_preview_without_redecoding(self):
        out = ensure_preview_cached(self.original)
        # 把预览改成一张可识别的 1x1 图：若被重新生成就会被覆盖掉
        cv2.imwrite(out, np.zeros((1, 1, 3), dtype=np.uint8))
        with open(out, "rb") as f:
            sentinel = f.read()

        again = ensure_preview_cached(self.original)

        self.assertEqual(again, out)
        with open(out, "rb") as f:
            self.assertEqual(f.read(), sentinel)

    def test_missing_original_returns_none(self):
        self.assertIsNone(ensure_preview_cached(os.path.join(self.tmp, "nope.png")))
        self.assertIsNone(ensure_preview_cached(""))

    def test_undecodable_original_is_negatively_cached(self):
        broken = os.path.join(self.tmp, "broken.tif")
        with open(broken, "wb") as f:
            f.write(b"not an image at all")

        self.assertIsNone(ensure_preview_cached(broken))
        self.assertFalse(os.path.exists(preview_path_for(broken)))
        # 第二次调用应命中负缓存，不再尝试解码
        self.assertIn(broken, _failed)
        self.assertIsNone(ensure_preview_cached(broken))

    def test_failed_cache_is_dropped_when_original_changes(self):
        broken = os.path.join(self.tmp, "later-ok.png")
        with open(broken, "wb") as f:
            f.write(b"garbage")
        self.assertIsNone(ensure_preview_cached(broken))
        self.assertIn(broken, _failed)

        # 原图被换成合法图片（mtime 变化）后应重试并成功
        _write_png(broken, size=(80, 60))
        bump = os.path.getmtime(broken) + 5
        os.utime(broken, (bump, bump))

        got = ensure_preview_cached(broken)
        self.assertEqual(got, preview_path_for(broken))
        self.assertTrue(os.path.exists(got))
        self.assertNotIn(broken, _failed)

    def test_preview_suffix_constant_is_used(self):
        self.assertTrue(preview_path_for("c.tif").endswith(PREVIEW_SUFFIX))
        self.assertEqual(preview_path_for("c.tif"), "c" + PREVIEW_SUFFIX)
        self.assertEqual(preview_path_for(os.path.join("a", "c.tif")),
                         os.path.join("a", "c" + PREVIEW_SUFFIX))


if __name__ == "__main__":
    unittest.main()
