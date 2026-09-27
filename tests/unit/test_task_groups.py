"""分析大类（茎秆 / 剑叶）分域回归测试。

前端"茎秆分析 / 剑叶分析"两个页面要求**严格分域**：历史接口按大类过滤，
非法大类直接报 400 而不是静默回退成"全部"，避免一类页面里看到另一类的记录。
"""
import unittest

from fastapi import HTTPException
from sqlmodel import select

from app.api.endpoints import analysis_router
from app.models.analysis import Analysis


def _all_task_keys():
    from app.core.tasks import get_tasks

    return list(get_tasks().keys())


class TaskGroupRegistryTests(unittest.TestCase):
    def test_groups_are_stem_and_leaf(self):
        from app.core.tasks import TASK_GROUPS

        self.assertEqual(TASK_GROUPS, ("stem", "leaf"))

    def test_stem_group_contains_only_stem_task(self):
        from app.core.tasks import task_types_of_group

        self.assertEqual(task_types_of_group("stem"), ["stem"])

    def test_leaf_group_contains_all_leaf_variants(self):
        from app.core.tasks import task_types_of_group

        leaf = task_types_of_group("leaf")

        for key in ("leaf", "leaf_our", "leaf_v11_head", "leaf_v11_p2_head",
                    "leaf_asf", "leaf_svbdet", "leaf_sod", "leaf_subtle"):
            with self.subTest(key=key):
                self.assertIn(key, leaf)
        self.assertNotIn("stem", leaf)

    def test_groups_cover_every_task_exactly_once(self):
        from app.core.tasks import task_types_of_group

        stem = task_types_of_group("stem")
        leaf = task_types_of_group("leaf")

        self.assertEqual(set(stem) & set(leaf), set())
        self.assertEqual(set(stem) | set(leaf), set(_all_task_keys()))
        # 后端共 10 个任务：1 个茎秆 + 9 个剑叶
        self.assertEqual(len(stem) + len(leaf), 10)

    def test_group_is_derived_from_metrics(self):
        from app.core.tasks import get_task

        self.assertEqual(get_task("stem").group, "stem")
        self.assertEqual(get_task("leaf_our").group, "leaf")

    def test_no_group_means_no_filter(self):
        from app.core.tasks import task_types_of_group

        for empty in (None, "", "   "):
            with self.subTest(value=empty):
                self.assertIsNone(task_types_of_group(empty))

    def test_unknown_group_is_rejected_not_defaulted(self):
        from app.core.tasks import is_valid_task_group, normalize_task_group, task_types_of_group

        self.assertFalse(is_valid_task_group("root"))
        self.assertFalse(is_valid_task_group(None))
        self.assertIsNone(normalize_task_group("root"))
        # 关键：未知大类不能退化成"不过滤"，否则分域失效
        self.assertIsNone(task_types_of_group("root"))

    def test_group_parsing_is_case_and_space_insensitive(self):
        from app.core.tasks import normalize_task_group

        self.assertEqual(normalize_task_group(" LEAF "), "leaf")
        self.assertEqual(normalize_task_group("Stem"), "stem")

    def test_list_tasks_carries_group_and_can_be_filtered(self):
        from app.core.tasks import list_tasks

        all_tasks = list_tasks()
        self.assertEqual(len(all_tasks), len(_all_task_keys()))
        for task in all_tasks:
            with self.subTest(task=task["key"]):
                self.assertIn(task["group"], ("stem", "leaf"))

        stem_tasks = list_tasks("stem")
        self.assertEqual([t["key"] for t in stem_tasks], ["stem"])

        leaf_tasks = list_tasks("leaf")
        self.assertTrue(all(t["group"] == "leaf" for t in leaf_tasks))
        self.assertNotIn("stem", [t["key"] for t in leaf_tasks])


class HistoryScopeTests(unittest.TestCase):
    """历史接口的分域行为：未知大类 400，合法大类只查本类的 task_type。

    这里直接调用接口函数并把 db.execute 换成一个捕获器，断言**真实构造出来的 SQL**，
    而不是复刻一份筛选逻辑（否则测的是测试自己的实现）。
    """

    class _CapturingDb:
        def __init__(self):
            self.statement = None

        async def execute(self, statement):
            self.statement = statement
            raise _StopAfterCapture

    def _query_for(self, **kwargs):
        """返回 (SQL 文本, 绑定参数集合)。

        用编译后的绑定参数而不是 literal_binds：task_type 是 VARCHAR 可以内联，
        但 user_id 是 UUID/主键，literal_binds 会直接编译失败。
        IN 子句的参数值在 params 里是 list，这里展开成一维。
        """
        import asyncio

        db = self._CapturingDb()
        with self.assertRaises(_StopAfterCapture):
            asyncio.run(analysis_router.get_analysis_history(
                request=None,
                user=type("U", (), {"id": "u1"})(),
                db=db,
                **kwargs,
            ))
        compiled = db.statement.compile()
        values = set()
        for value in compiled.params.values():
            if isinstance(value, (list, tuple, set)):
                values.update(str(v) for v in value)
            else:
                values.add(str(value))
        return str(compiled), values

    def test_no_scope_returns_everything(self):
        sql, params = self._query_for()

        self.assertNotIn("task_type IN", sql)
        self.assertNotIn("analyses.task_type =", sql)
        self.assertNotIn("stem", params)
        self.assertNotIn("leaf_our", params)

    def test_stem_scope_only_queries_stem(self):
        sql, params = self._query_for(group="stem")

        self.assertIn("analyses.task_type IN", sql)
        self.assertEqual(params - {"u1"}, {"stem"})

    def test_whitespace_task_type_keeps_the_explicit_empty_filter(self):
        sql, params = self._query_for(task_type=" ")
        self.assertIn("analyses.task_type =", sql)
        self.assertEqual(params - {"u1"}, {""})

    def test_leaf_scope_excludes_stem_records(self):
        sql, params = self._query_for(group="leaf")

        self.assertIn("analyses.task_type IN", sql)
        # 剑叶分支绑定的全部是剑叶类型，绝不含 stem
        self.assertNotIn("stem", params)
        self.assertIn("leaf_our", params)
        self.assertIn("leaf_v11_head", params)
        self.assertEqual(params - {"u1"}, set(_leaf_keys()))

    def test_group_is_case_insensitive(self):
        _sql, params = self._query_for(group=" LEAF ")

        self.assertEqual(params - {"u1"}, set(_leaf_keys()))

    def test_unknown_group_raises_400_without_querying(self):
        import asyncio

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(analysis_router.get_analysis_history(
                request=None,
                group="root",
                user=type("U", (), {"id": "u1"})(),
                db=self._CapturingDb(),
            ))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_task_type_wins_over_group(self):
        sql, params = self._query_for(task_type="leaf_our", group="stem")

        self.assertIn("analyses.task_type =", sql)
        self.assertEqual(params - {"u1"}, {"leaf_our"})


def _leaf_keys():
    from app.core.tasks import task_types_of_group

    return task_types_of_group("leaf")


class _StopAfterCapture(Exception):
    """哨兵异常：捕获到 SQL 后立刻终止接口函数，不进入后续处理。"""


if __name__ == "__main__":
    unittest.main()
