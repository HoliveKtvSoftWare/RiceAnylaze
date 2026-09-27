import unittest


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_public_router_and_legacy_router_share_routes(self):
        from app.api.routers import analysis
        from app.api.endpoints import analysis_router

        self.assertIs(analysis.router, analysis_router.router)

    def test_storage_compatibility_helpers_are_shared(self):
        from app.api.endpoints.analysis_router import _files_of_analysis
        from app.infrastructure.storage.files import files_of_analysis

        self.assertIs(_files_of_analysis, files_of_analysis)

    def test_export_feature_preserves_singleton(self):
        from app.features.export.excel import excel_service
        from app.services.excel_download import excel_service as legacy_service

        self.assertIs(excel_service, legacy_service)

    def test_queue_compatibility_path_shares_mutable_state(self):
        from app.features.analysis import queue
        from app.services import analysis_queue

        self.assertIs(queue, analysis_queue)

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
