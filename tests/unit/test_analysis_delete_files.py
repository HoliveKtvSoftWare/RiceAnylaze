"""删除分析记录时的磁盘文件清理回归测试。

背景：原图预览图（`<名称>.preview.jpg`）在数据库里没有字段，路径只能由
`original_file_path` 推导。此前**批量删除**接口漏了这一步，导致删除记录后
预览图变成孤儿文件留在静态目录里（线上日志里能看到对应的 404）。
"""
import os
import shutil
import types
import unittest

from app.infrastructure.storage.files import (
    files_of_analysis as _files_of_analysis,
    remove_files as _remove_files,
)
from app.infrastructure.storage.previews import preview_path_for

# 临时目录放在工作区内：受限环境下系统 TEMP 可能不可写
TEST_TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp")


def _record(original=None, annotated=None, result_json=None):
    """用 SimpleNamespace 冒充 Analysis 记录：这两个 helper 只读这三个字段。"""
    return types.SimpleNamespace(
        original_file_path=original,
        annotated_image_path=annotated,
        result_json_path=result_json,
    )


class FilesOfAnalysisTests(unittest.TestCase):
    def test_includes_preview_derived_from_original(self):
        original = os.path.join("app_storage", "originals", "u1", "abc_10-1.tif")

        files = _files_of_analysis(_record(original, "annotated.jpg", "result.json"))

        self.assertIn(original, files)
        self.assertIn("annotated.jpg", files)
        self.assertIn("result.json", files)
        self.assertIn(preview_path_for(original), files)

    def test_without_original_has_no_preview_entry(self):
        files = _files_of_analysis(_record(None, "annotated.jpg", None))

        self.assertEqual(files, ["annotated.jpg"])
        self.assertNotIn(None, files)

    def test_none_fields_are_filtered_out(self):
        self.assertEqual(_files_of_analysis(_record()), [])


class RemoveFilesTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(TEST_TMP_ROOT, exist_ok=True)
        self.tmp = os.path.join(TEST_TMP_ROOT, self._testMethodName)
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _touch(self, name):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("x")
        return path

    def test_removes_preview_together_with_original(self):
        original = self._touch("abc_10-1.tif")
        preview = self._touch("abc_10-1.preview.jpg")
        annotated = self._touch("abc_10-1.jpg")

        record = _record(original, annotated, None)
        _remove_files(_files_of_analysis(record))

        for path in (original, preview, annotated):
            self.assertFalse(os.path.exists(path), path)

    def test_missing_files_are_ignored(self):
        original = self._touch("keep-me.tif")
        # 预览不存在：不应抛异常
        _remove_files(_files_of_analysis(_record(original)))
        self.assertFalse(os.path.exists(original))

    def test_directory_entry_does_not_abort_cleanup(self):
        victim = self._touch("a.tif")
        subdir = os.path.join(self.tmp, "a.preview.jpg")   # 目录冒充预览文件
        os.makedirs(subdir)

        # 删除目录会失败，但异常被吞掉，后续文件仍需删掉
        _remove_files([subdir, victim])

        self.assertTrue(os.path.isdir(subdir))
        self.assertFalse(os.path.exists(victim))


if __name__ == "__main__":
    unittest.main()
