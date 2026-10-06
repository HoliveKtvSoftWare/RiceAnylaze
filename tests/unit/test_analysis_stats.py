"""主页统计工具（`app/features/analysis/statistics_service.py`）回归测试。

覆盖：任务大类归属、耗时计算（含缺失/负值/时区混用）、近 N 天按日分桶。
"""
import unittest
from datetime import datetime, timedelta, timezone


class _Record:
    def __init__(self, created_at=None, status='completed', task_type='stem'):
        self.created_at = created_at
        self.status = status
        self.task_type = task_type


class GroupOfTaskTypeTests(unittest.TestCase):
    def test_stem_maps_to_stem(self):
        from app.features.analysis.statistics_service import group_of_task_type

        self.assertEqual(group_of_task_type('stem'), 'stem')
        self.assertEqual(group_of_task_type(' STEM '), 'stem')

    def test_leaf_variants_map_to_leaf(self):
        from app.features.analysis.statistics_service import group_of_task_type

        for key in ('leaf', 'leaf_our', 'leaf_v11_head', 'leaf_svbdet', 'leaf_asf'):
            with self.subTest(key=key):
                self.assertEqual(group_of_task_type(key), 'leaf')

    def test_unknown_type_is_reported_as_unknown(self):
        from app.features.analysis.statistics_service import group_of_task_type

        # 未登记的类型归为 unknown，不猜成某一类：猜错会让两个族的统计口径悄悄串台
        self.assertEqual(group_of_task_type('something_new'), 'unknown')
        self.assertEqual(group_of_task_type(None), 'unknown')


class DurationTests(unittest.TestCase):
    def test_normal_duration(self):
        from app.features.analysis.statistics_service import duration_seconds

        start = datetime(2026, 9, 17, 10, 0, 0)
        self.assertEqual(duration_seconds(start, start + timedelta(seconds=8.5)), 8.5)

    def test_missing_side_returns_none(self):
        from app.features.analysis.statistics_service import duration_seconds

        start = datetime(2026, 9, 17, 10, 0, 0)
        # 老记录没有 started_at / finished_at：必须跳过而不是当成 0 秒
        self.assertIsNone(duration_seconds(None, start))
        self.assertIsNone(duration_seconds(start, None))
        self.assertIsNone(duration_seconds(None, None))

    def test_negative_duration_returns_none(self):
        from app.features.analysis.statistics_service import duration_seconds

        start = datetime(2026, 9, 17, 10, 0, 10)
        self.assertIsNone(duration_seconds(start, start - timedelta(seconds=5)))

    def test_timezone_aware_values_are_normalized(self):
        from app.features.analysis.statistics_service import duration_seconds

        start = datetime(2026, 9, 17, 10, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 9, 17, 18, 0, 5, tzinfo=timezone(timedelta(hours=8)))

        # naive 与 aware 混用不能让减法炸掉，且结果按同一时刻计算
        self.assertEqual(duration_seconds(start, end), 5.0)


class DailySeriesTests(unittest.TestCase):
    def setUp(self):
        # 固定"现在"：北京时间 2026-09-17 12:00 == UTC 04:00
        self.now_utc = datetime(2026, 9, 17, 4, 0, 0)

    def test_series_has_window_days_and_ends_today(self):
        from app.features.analysis.statistics_service import build_daily_series

        daily = build_daily_series([], window_days=7, now_utc=self.now_utc)

        self.assertEqual(len(daily), 7)
        self.assertEqual(daily[-1]['date'], '2026-09-17')
        self.assertEqual(daily[0]['date'], '2026-09-11')
        self.assertTrue(all(item['total'] == 0 for item in daily))

    def test_records_are_bucketed_by_local_day(self):
        from app.features.analysis.statistics_service import build_daily_series

        records = [
            # UTC 2026-09-17 01:00 -> 北京 09:00 当天
            _Record(datetime(2026, 9, 17, 1, 0), 'completed'),
            # UTC 2026-09-16 20:00 -> 北京 09-17 04:00，仍算 17 日（跨越 UTC 日界）
            _Record(datetime(2026, 9, 16, 20, 0), 'failed'),
            # UTC 2026-09-16 01:00 -> 北京 09-16 09:00
            _Record(datetime(2026, 9, 16, 1, 0), 'completed'),
        ]

        daily = build_daily_series(records, window_days=7, now_utc=self.now_utc)
        by_date = {item['date']: item for item in daily}

        self.assertEqual(by_date['2026-09-17']['total'], 2)
        self.assertEqual(by_date['2026-09-17']['completed'], 1)
        self.assertEqual(by_date['2026-09-17']['failed'], 1)
        self.assertEqual(by_date['2026-09-16']['total'], 1)
        self.assertEqual(
            sum(item['total'] for item in daily), 3, '窗口内的记录不应丢失'
        )

    def test_records_outside_window_are_ignored(self):
        from app.features.analysis.statistics_service import build_daily_series

        old = self.now_utc - timedelta(days=30)
        daily = build_daily_series([_Record(old, 'completed')], window_days=7, now_utc=self.now_utc)

        self.assertEqual(sum(item['total'] for item in daily), 0)

    def test_record_without_created_at_is_ignored(self):
        from app.features.analysis.statistics_service import build_daily_series

        daily = build_daily_series([_Record(None, 'completed')], window_days=7, now_utc=self.now_utc)

        self.assertEqual(sum(item['total'] for item in daily), 0)

    def test_window_is_at_least_one_day(self):
        from app.features.analysis.statistics_service import build_daily_series

        # 非法/过小的窗口至少给 1 天，不能返回空序列（前端要画柱子）
        self.assertEqual(len(build_daily_series([], window_days=0, now_utc=self.now_utc)), 1)
        self.assertEqual(len(build_daily_series([], window_days=-5, now_utc=self.now_utc)), 1)
        # 接口层另有 1~90 的上限（见 /api/analysis/stats?days=），这里不重复限制
        self.assertEqual(len(build_daily_series([], window_days=30, now_utc=self.now_utc)), 30)


if __name__ == '__main__':
    unittest.main()
