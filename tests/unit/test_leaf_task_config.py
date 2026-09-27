import unittest


class LeafTaskPostprocessConfigTests(unittest.TestCase):
    def test_all_leaf_tasks_enable_topology_side_validation_and_preview_smoothing(self):
        from app.core.tasks import get_tasks

        leaf_tasks = [task for task in get_tasks().values() if task.metrics == "leaf"]

        self.assertTrue(leaf_tasks)
        for task in leaf_tasks:
            with self.subTest(task=task.key):
                self.assertIs(getattr(task, "preserve_mask_topology", None), True)
                self.assertIs(getattr(task, "validate_side_bundles", None), True)
                self.assertIs(getattr(task, "preview_smooth", None), True)

    def test_stem_task_keeps_new_postprocess_disabled(self):
        from app.core.tasks import get_task

        stem = get_task("stem")

        self.assertIs(getattr(stem, "preserve_mask_topology", None), False)
        self.assertIs(getattr(stem, "validate_side_bundles", None), False)
        self.assertIs(getattr(stem, "preview_smooth", None), False)


if __name__ == "__main__":
    unittest.main()
