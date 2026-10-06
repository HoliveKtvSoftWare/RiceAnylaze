# -*- coding: utf-8 -*-
"""族解耦的边界回归测试。

目的：茎秆与剑叶（以及将来的第三个大类）能各自独立维护、互不牵连。
这里用机器可检查的方式守住四件事：

1. **共享核心里不出现具体族名** —— 否则"加一个族要改好几处"会慢慢长回来
2. **每个族都提供完整接口**（specs / columns / compute_metrics）
3. **加一个族不需要改共享核心** —— 用一个内存假族证明
4. **列定义与指标算法不脱节** —— 算法产出的每个 key 都要有对应的列
"""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from app.features.task_catalog import registry
from app.features.task_catalog.families import ALL_FAMILIES

ROOT = Path(__file__).resolve().parents[2]

# 共享核心：这些文件必须"族无关"。族专属的东西应放在
# features/task_catalog/families/ 与 domain/analysis/families/ 里。
SHARED_CORE = (
    "app/features/task_catalog/types.py",
    "app/features/task_catalog/registry.py",
    "app/features/export/excel.py",
    "app/features/export/service.py",
    "app/features/analysis/history_service.py",
    "app/features/analysis/statistics_service.py",
    "app/domain/analysis/metrics_common.py",
)


def _exact_string_literals(relative_path):
    """产出该文件里"整体等于某个字符串"的字面量（不含长文档里的引用）。"""
    source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


class SharedCoreIsFamilyAgnosticTests(unittest.TestCase):
    def test_shared_core_never_names_a_family(self):
        family_names = {family.key for family in ALL_FAMILIES}
        offenders = []
        for relative_path in SHARED_CORE:
            for lineno, value in _exact_string_literals(relative_path):
                if value.strip().lower() in family_names:
                    offenders.append("{}:{}  {!r}".format(relative_path, lineno, value))
        self.assertEqual(
            offenders, [],
            "共享核心里出现了具体族名，说明又耦合回去了：\n" + "\n".join(offenders),
        )

    def test_shared_core_does_not_import_concrete_families(self):
        """核心只能通过 registry / TaskFamily 接口访问族。

        唯一的例外是 registry 聚合 ``families/__init__.py`` 里的 ``ALL_FAMILIES``
        （这正是"注册表"的职责）；直接 import 某个具体族（``...families.stem``）
        或按名字取族模块都算耦合。
        """
        offenders = []
        for relative_path in SHARED_CORE:
            source = (ROOT / relative_path).read_text(encoding="utf-8-sig")
            for node in ast.walk(ast.parse(source)):
                if not (isinstance(node, ast.ImportFrom) and node.module):
                    continue
                parts = node.module.split(".")
                if "families" not in parts:
                    continue
                after_families = parts[parts.index("families") + 1:]
                names = {alias.name for alias in node.names}
                if after_families or names - {"ALL_FAMILIES"}:
                    offenders.append("{}:{}  from {} import {}".format(
                        relative_path, node.lineno, node.module, ", ".join(sorted(names))))
        self.assertEqual(offenders, [], "\n".join(offenders))


class FamilyInterfaceTests(unittest.TestCase):
    def test_every_family_provides_the_full_interface(self):
        self.assertTrue(ALL_FAMILIES, "至少要注册一个族")
        for family in ALL_FAMILIES:
            with self.subTest(family=family.key):
                self.assertTrue(family.key)
                self.assertTrue(family.label)
                self.assertTrue(callable(family.specs))
                self.assertTrue(callable(family.compute_metrics))
                self.assertIsInstance(family.columns, dict)
                self.assertTrue(family.columns)
                self.assertTrue(family.specs(), "每个族至少有一个任务")

    def test_every_task_belongs_to_a_registered_family(self):
        registered = {family.key for family in ALL_FAMILIES}
        for spec in registry.get_tasks().values():
            with self.subTest(task=spec.key):
                self.assertIn(spec.group, registered)

    def test_family_lookup_accepts_group_and_task_key(self):
        for family in ALL_FAMILIES:
            with self.subTest(family=family.key):
                self.assertIs(registry.family_of(family.key), family)
                for spec in family.specs():
                    self.assertIs(registry.family_of(spec.key), family)


class ColumnsMatchMetricsTests(unittest.TestCase):
    def test_metric_output_has_a_column_for_every_key(self):
        """算法算出来的每个 key 都必须能在列定义里找到，否则导出时会静默变成 N/A。"""
        sample = {"shapes": [
            {"label": label, "points": [[0, 0], [8, 0], [8, 4], [0, 4]], "flags": {}}
            for label in ["big", "small", "in", "out",
                          "body1", "body2", "side1", "side2",
                          "body_big", "body1_small", "body2_small",
                          "side1_big", "side1_small", "side2_big", "side2_small"]
        ]}
        for family in ALL_FAMILIES:
            with self.subTest(family=family.key):
                produced = set(family.compute_metrics(sample, "um", 1.0))
                missing = sorted(produced - set(family.columns))
                self.assertEqual(missing, [],
                                 "族 {} 的指标产出了列定义里没有的 key: {}".format(family.key, missing))


class AddingAFamilyNeedsNoCoreChangeTests(unittest.TestCase):
    """用一个临时假族证明「加族 = 加文件 + 注册一行」，共享核心一行都不用改。"""

    def _fake_family(self):
        from app.features.task_catalog.types import TaskFamily, TaskSpec

        return TaskFamily(
            key="fake",
            label="假族",
            columns={"filename": "样本名称", "demoCount": "示例计数"},
            specs=lambda: [TaskSpec(key="fake_task", name="假任务", group="fake",
                                    model_path="fake.pt", colors={})],
            compute_metrics=lambda data, unit, scale: {"demoCount": len(data.get("shapes", []))},
        )

    def test_registry_serves_a_newly_registered_family(self):
        fake = self._fake_family()
        with patch.object(registry, "ALL_FAMILIES", ALL_FAMILIES + (fake,)):
            self.assertIn("fake_task", registry.get_tasks())
            self.assertIs(registry.family_of("fake_task"), fake)
            self.assertIs(registry.family_of("fake"), fake)
            self.assertEqual(registry.columns_for("fake_task"), fake.columns)
            self.assertEqual(
                registry.compute_metrics("fake_task", {"shapes": [1, 2, 3]}, "um", 1.0),
                {"demoCount": 3},
            )
            self.assertEqual([t["key"] for t in registry.list_tasks("fake")], ["fake_task"])
            self.assertEqual([m["key"] for m in registry.list_models("fake")], ["fake_task"])


if __name__ == "__main__":
    unittest.main()
