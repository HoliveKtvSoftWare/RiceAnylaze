import importlib
import unittest
from unittest.mock import mock_open, patch


class InferenceRefactorTests(unittest.TestCase):
    def test_new_modules_expose_split_pipeline_and_legacy_aliases(self):
        labelme = importlib.import_module("app.infrastructure.inference.labelme")
        renderer = importlib.import_module("app.infrastructure.inference.renderer")
        runner = importlib.import_module("app.infrastructure.inference.runner")
        legacy = importlib.import_module("app.services.yolo_inference")

        self.assertIs(legacy.convert_to_labelme_format, labelme.convert_to_labelme_format)
        self.assertIs(legacy.draw_polygons_on_image, renderer.draw_polygons_on_image)
        self.assertIs(legacy.run_system, runner.run_system)

    def test_task_catalog_is_the_source_of_legacy_registry_exports(self):
        catalog = importlib.import_module("app.features.task_catalog.catalog")
        legacy = importlib.import_module("app.core.tasks")

        self.assertIs(legacy.get_task, catalog.get_task)
        self.assertIs(legacy.TaskSpec, catalog.TaskSpec)

    def test_sidecar_reports_missing_result_file_and_preserves_protocol(self):
        from app.features.task_catalog.types import TaskSpec
        from app.infrastructure.inference.sidecar import _task_spec, run_via_sidecar

        task = TaskSpec("test", "Test", "model.pt", {"out": (1, 2, 3, 4)})
        self.assertEqual(_task_spec(task)["colors"], {"out": [1, 2, 3, 4]})
        with patch("app.infrastructure.inference.sidecar.open", mock_open()), \
                patch("app.infrastructure.inference.sidecar.os.path.exists", return_value=False), \
                patch("app.infrastructure.inference.sidecar.subprocess.run") as run:
            run.return_value.returncode = 9
            with self.assertRaisesRegex(RuntimeError, "did not produce result file"):
                run_via_sidecar(task, "image.jpg", "output", "sample")
        self.assertEqual(run.call_args.kwargs["timeout"], 3600)

    def test_native_predict_preserves_ultralytics_arguments(self):
        from app.infrastructure.inference.native import predict

        calls = []

        def model(image_path, **kwargs):
            calls.append((image_path, kwargs))
            return ["result"]

        self.assertEqual(predict(model, "image.jpg", None, 0.4, 0.5, True), ["result"])
        self.assertEqual(calls, [("image.jpg", {
            "show": False, "save": False, "visualize": False,
            "conf": 0.4, "iou": 0.5, "retina_masks": True,
        })])

    def test_sidecar_returns_paths_from_success_result(self):
        from app.features.task_catalog.types import TaskSpec
        from app.infrastructure.inference.sidecar import run_via_sidecar

        task = TaskSpec("test", "Test", "model.pt", {})
        result = '{"ok": true, "annotated_image_path": "a.jpg", "result_json_path": "a.json"}'
        handle = mock_open(read_data=result)
        with patch("app.infrastructure.inference.sidecar.open", handle), \
                patch("app.infrastructure.inference.sidecar.os.path.exists", side_effect=[False, False, False, True]), \
                patch("app.infrastructure.inference.sidecar.subprocess.run"):
            paths = run_via_sidecar(task, "image.jpg", "output", "sample")
        self.assertEqual(paths, ("a.jpg", "a.json"))


if __name__ == "__main__":
    unittest.main()
