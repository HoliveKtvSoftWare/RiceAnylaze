"""架构边界回归测试。

原来这里还有 3 个"兼容转发模块与新模块是同一个对象"的断言。那些转发模块
（`app.services.analysis_queue` / `excel_download` / `api.endpoints.analysis_router`）
只被本仓库的测试引用，已经删除，断言也随之移除。保留下来的这一类测试针对的是
仍然存在的转发模块。
"""
import unittest


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_analysis_service_preserves_configured_sidecar_paths(self):
        from unittest.mock import mock_open, patch
        from app.features.analysis import service
        from app.features.task_catalog.catalog import get_task

        result = '{"ok": true, "annotated_image_path": "a.jpg", "result_json_path": "a.json"}'
        with patch.object(service.settings, "FORK_PYTHON", "custom-python"), \
                patch.object(service.settings, "SIDECAR_SCRIPT", "custom-sidecar.py"), \
                patch.object(service.settings, "FORK_PROJECT", "custom-runtime"), \
                patch.object(service.settings, "FORK_PYLIBS", "custom-libs"), \
                patch("app.infrastructure.inference.sidecar.open", mock_open(read_data=result)), \
                patch("app.infrastructure.inference.sidecar.os.path.exists", side_effect=[False, False, False, True]), \
                patch("app.infrastructure.inference.sidecar.subprocess.run") as run:
            service._run_via_sidecar(get_task("leaf_our"), "image.jpg", "output", "sample")
        self.assertEqual(run.call_args.args[0][:2], ["custom-python", "custom-sidecar.py"])
        self.assertEqual(run.call_args.kwargs["env"]["RICE_FORK_PROJECT"], "custom-runtime")
        self.assertTrue(run.call_args.kwargs["env"]["PYTHONPATH"].startswith("custom-libs"))


if __name__ == "__main__":
    unittest.main()
