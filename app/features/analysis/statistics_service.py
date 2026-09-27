# -*- coding: utf-8 -*-
"""主页统计用的小工具：任务大类归属、耗时计算与"按自然日"分桶。

单独成模块是为了能脱离数据库直接单测（`tests/test_analysis_stats.py`）。
时间口径统一为 **UTC**：数据库里存的是不带时区的 UTC 时间，
展示时按北京时区（UTC+8）切自然日。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.features.task_catalog.catalog import TASK_GROUP_LEAF, TASK_GROUP_STEM, task_types_of_group

CN_OFFSET = timedelta(hours=8)


def group_of_task_type(task_type: Optional[str]) -> str:
    """任务类型属于哪个大类；未登记的按剑叶处理（与前端约定一致）。"""
    key = str(task_type or "").strip().lower()
    if key == TASK_GROUP_STEM:
        return TASK_GROUP_STEM
    if key in (task_types_of_group(TASK_GROUP_LEAF) or []):
        return TASK_GROUP_LEAF
    return TASK_GROUP_LEAF


def _ascii_utc(value: Optional[datetime]) -> Optional[datetime]:
    """统一成"不带时区的 UTC 时间"。

    数据库列是 naive UTC；但如果哪天换了带时区的类型，这里也不会把两种值混着相减。
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def duration_seconds(started_at: Optional[datetime],
                     finished_at: Optional[datetime]) -> Optional[float]:
    """推理耗时（秒）。任一端缺失、或出现负值（时钟回拨/异常数据）都返回 None。"""
    start = _ascii_utc(started_at)
    end = _ascii_utc(finished_at)
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return None
    return seconds


def local_date(value: Optional[datetime]) -> Optional[str]:
    """UTC 时间 -> 北京时区的自然日（YYYY-MM-DD）。"""
    ascii_utc = _ascii_utc(value)
    if ascii_utc is None:
        return None
    return (ascii_utc + CN_OFFSET).date().isoformat()


def build_daily_series(records: List[Any],
                       window_days: int = 7,
                       now_utc: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """近 window_days 天（含今天）的按日统计，缺日补 0。

    records 只需有 created_at / status 两个属性。
    """
    window = max(1, int(window_days))
    now_utc = _ascii_utc(now_utc) or datetime.utcnow()
    today_local = (now_utc + CN_OFFSET).date()

    daily: List[Dict[str, Any]] = []
    for offset in range(window - 1, -1, -1):
        day = today_local - timedelta(days=offset)
        daily.append({"date": day.isoformat(), "completed": 0, "failed": 0, "total": 0})

    index = {item["date"]: item for item in daily}
    window_start = now_utc - timedelta(days=window)
    for record in records:
        created = _ascii_utc(getattr(record, "created_at", None))
        if created is None or created < window_start:
            continue
        bucket = index.get(local_date(created))
        if not bucket:
            continue
        bucket["total"] += 1
        if getattr(record, "status", None) == "completed":
            bucket["completed"] += 1
        elif getattr(record, "status", None) == "failed":
            bucket["failed"] += 1

    return daily


async def get_analysis_stats(days, user, repository):
    """主页统计：总览计数、近 N 天完成趋势与平均推理耗时。

    days：趋势窗口（1~90，默认 7）。
    耗时为 finished_at - started_at，只统计两者都有的记录（老记录没有，自动跳过）。
    时间一律按 UTC 比较，按"北京时区（UTC+8）"切成自然日展示。
    """
    window = max(1, min(90, int(days or 7)))
    now_utc = datetime.utcnow()

    records = await repository.list(user.id, ordered=False)

    by_status: Dict[str, int] = {}
    by_group: Dict[str, int] = {"stem": 0, "leaf": 0}
    durations: List[float] = []
    for record in records:
        by_status[record.status] = by_status.get(record.status, 0) + 1
        group = group_of_task_type(record.task_type)
        by_group[group] = by_group.get(group, 0) + 1
        seconds = duration_seconds(record.started_at, record.finished_at)
        if seconds is not None:
            durations.append(seconds)

    return {
        "total": len(records),
        "byStatus": by_status,
        "byGroup": by_group,
        "avgDurationSeconds": round(sum(durations) / len(durations), 1) if durations else None,
        "measuredCount": len(durations),
        "windowDays": window,
        "daily": build_daily_series(records, window, now_utc),
    }
