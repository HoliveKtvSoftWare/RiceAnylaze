# -*- coding: utf-8 -*-
"""异步 Excel 导出任务：内存注册表 + 后台线程。

为什么需要它
------------
一次汇总导出要逐条读 JSON、算几十项指标再写 xlsx。记录一多就是几十秒的
纯 CPU/IO 工作，塞在事件循环里会把所有其它请求一起卡住（前端表现为整站转圈）。
所以超过阈值时前端传 ``asyncMode=true``：后端立刻返回 ``taskId``，真正的工作
丢到后台线程，前端轮询 ``/excel/tasks/{id}`` 看进度、完成后走
``/excel/download/{id}`` 下载。

几个刻意的取舍
--------------
* **用线程不用 asyncio task**：导出走的是 pandas/openpyxl 同步栈，放进线程才能真正
  不阻塞事件循环（和推理队列用线程的理由不同，那边是为了串行化）。
* **注册表只在进程内存里**：重启即失效，未完成的任务随进程消失。这与上游实现
  一致；导出是可重试的操作，不值得为它引入 Redis。
* **落盘目录不放 STORAGE_PATH**：``STORAGE_PATH`` 挂在 ``/static`` 上是公开可读的，
  导出结果放进去等于把别人的数据暴露成静态资源。
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.features.export.excel import excel_service
from app.features.task_catalog.catalog import get_task

log = logging.getLogger(__name__)

_tasks: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()

_EXPORT_DIR = os.path.join(tempfile.gettempdir(), "rice_export_tasks")


@dataclass
class RecordView:
    """后台线程里重建的最小记录视图。

    线程里没有 ORM 会话，不能带着脱离 session 的 Analysis 实例过去；
    ``load_record_data`` 只用到下面四个属性，所以这里给一个轻量替身。
    """

    analysis_id: str
    original_file_path: Optional[str]
    result_json_path: Optional[str]
    task_type: str


def label_prefix(task_type: str) -> str:
    """导出文件名前缀：茎秆 / 剑叶。"""
    try:
        return "剑叶" if get_task(task_type).group == "leaf" else "茎秆"
    except Exception:                                                 # noqa: BLE001
        return "分析"


def _update(task_id: str, **fields) -> None:
    with _lock:
        task = _tasks.get(task_id)
        if task is not None:
            task.update(fields)


def submit(records: List[Dict[str, Any]], selected_columns: List[str], unit: str,
           scale: float, task_type: str) -> str:
    """登记一个导出任务并启动后台线程，立刻返回 task_id。

    ``records`` 里每项至少要有 analysis_id / user_id / original_file_path /
    result_json_path / task_type —— 都在请求的 session 内取好，线程里不再查库。
    """
    task_id = str(uuid.uuid4())
    with _lock:
        _tasks[task_id] = {
            "status": "processing",
            "total": len(records),
            "progress": 0,
            "created_at": datetime.now().isoformat(),
            "file_path": None,
            "filename": None,
            "error": None,
        }
    threading.Thread(
        target=_run,
        args=(task_id, records, selected_columns, unit, scale, task_type),
        name="excel-export-{}".format(task_id[:8]),
        daemon=True,
    ).start()
    log.info("导出任务 %s 已提交（%s 条记录，类型 %s）", task_id, len(records), task_type)
    return task_id


def get(task_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        task = _tasks.get(task_id)
        return dict(task) if task else None


def result(task_id: str) -> Optional[Tuple[str, str]]:
    """已完成任务的 ``(文件路径, 文件名)``；未完成或不存在返回 None。"""
    with _lock:
        task = _tasks.get(task_id)
    if not task or task["status"] != "completed":
        return None
    return task["file_path"], task["filename"]


def _run(task_id: str, records: List[Dict[str, Any]], selected_columns: List[str],
         unit: str, scale: float, task_type: str) -> None:
    try:
        valid_data = []
        for index, info in enumerate(records):
            try:
                view = RecordView(
                    analysis_id=info["analysis_id"],
                    original_file_path=info.get("original_file_path"),
                    result_json_path=info.get("result_json_path"),
                    task_type=info.get("task_type") or task_type,
                )
                valid_data.append(excel_service.load_record_data(
                    view, info["user_id"], unit, scale, task_type))
            except Exception as exc:                                  # noqa: BLE001
                # 单条坏数据（JSON 丢了、图丢了）不该让整批导出失败
                log.warning("异步导出跳过记录 %s: %s", info.get("analysis_id"), exc)
            _update(task_id, progress=index + 1)

        if not valid_data:
            _update(task_id, status="failed", error="没有成功加载任何分析数据")
            return

        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = "{}_{}个文件{}_{}.xlsx".format(
            label_prefix(task_type), len(valid_data), now_str, unit)

        buffer = excel_service.export_all_to_excel(valid_data, selected_columns, task_type)
        os.makedirs(_EXPORT_DIR, exist_ok=True)
        file_path = os.path.join(_EXPORT_DIR, "{}.xlsx".format(task_id))
        with open(file_path, "wb") as handle:
            handle.write(buffer.getvalue())

        _update(task_id, status="completed", file_path=file_path,
                filename=filename, progress=len(records))
        log.info("导出任务 %s 完成: %s（成功 %s/%s）",
                 task_id, file_path, len(valid_data), len(records))

    except Exception as exc:                                          # noqa: BLE001
        log.error("导出任务 %s 失败: %s", task_id, exc, exc_info=True)
        _update(task_id, status="failed", error=str(exc))


__all__ = ["RecordView", "submit", "get", "result", "label_prefix"]
