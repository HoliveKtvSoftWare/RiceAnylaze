# -*- coding: utf-8 -*-
"""全局**串行**分析队列（单 worker 线程）。

为什么需要它
------------
原来上传接口用 FastAPI `BackgroundTasks` 派发推理。FastAPI/Starlette 对**同一个请求**
里的多个后台任务确实是顺序执行的，但多个请求（例如前端分批发出的 5 次 upload）各自的后台
任务会**并发**跑起来。而一次推理在 `fork` 任务下是"起一个子进程 + 加载一份 140MB 权重"，
native 任务也要在进程内加载模型 —— 5 张图同时起步就是 5 份模型内存，普通机器直接卡死
（实测已发生）。

做法
----
后端维护**唯一的**工作线程 + 一个 FIFO 队列：

    enqueue_analysis(...)   入队，立刻返回（同步、线程安全）
    _worker_loop()          一次只取一个，跑完再取下一个

为什么用线程而不是 asyncio task：队列要在**同步**上下文里也能用（上传接口、启动时的遗留
清理），而 `asyncio.Queue` 必须绑定事件循环（Python 3.8 下在同步上下文里创建还会直接
抛错）。线程 + `collections.deque` 没有这个问题，且"一个 worker 线程"本身就保证了串行。

队列在进程内存里，**后端重启会丢失尚未开始的任务**；重启时由
`requeue_pending_on_startup()` 收拾残留记录（原图还在的会重新排队）。
"""

from __future__ import annotations

import collections
import logging
import os
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.infrastructure.database.session import sync_engine
from app.models.analysis import Analysis

log = logging.getLogger(__name__)

# 队列项：(analysis_id, 入队参数)
_QueueItem = Tuple[str, Dict[str, Any]]

_queue: "collections.deque[_QueueItem]" = collections.deque()
# 有新任务 / 需要退出时唤醒 worker 线程
_wakeup = threading.Event()
_shutdown = threading.Event()
_worker: Optional[threading.Thread] = None
_lock = threading.Lock()
# 每个任务在队列中的序号，用于给前端显示"前面还有几个"
_seq_counter = 0
# 当前正在执行的任务（没有则为 None）
_current_id: Optional[str] = None


def start_worker() -> None:
    """启动唯一的队列 worker 线程（重复调用无副作用）。"""
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _shutdown.clear()
        _wakeup.clear()
        _worker = threading.Thread(target=_worker_loop, name="analysis-queue-worker", daemon=True)
        _worker.start()
    log.info("分析队列已启动（单 worker 线程，任务串行执行）")


def stop_worker(timeout: float = 5.0) -> None:
    """停止 worker 线程。

    注意：**不会**打断正在跑的推理（它就在这个线程里），所以只等一小会儿；
    未开始的任务随进程一起结束（daemon 线程不阻塞退出）。
    """
    global _worker
    with _lock:
        worker, _worker = _worker, None
    _shutdown.set()
    _wakeup.set()
    if worker is not None and worker.is_alive():
        worker.join(timeout=timeout)
        if worker.is_alive():
            log.warning("分析队列 worker 在 %.1fs 内未退出（推理可能仍在进行）", timeout)
    log.info("分析队列已停止")


def enqueue_analysis(analysis_id: str, payload: Dict[str, Any]) -> int:
    """把一次分析排到队尾，返回它的**排号**（从 1 开始）。

    同步、线程安全，可在请求处理函数或启动清理里直接调用。
    """
    global _seq_counter
    with _lock:
        _seq_counter += 1
        position = _seq_counter
        _queue.append((str(analysis_id), payload))
        size = len(_queue)
    _wakeup.set()
    log.info("分析任务已入队: %s（排号 %s，当前队列长度 %s）", analysis_id, position, size)
    return position


def pending_count() -> int:
    """当前排队中的任务数（不含正在执行的那个）。"""
    with _lock:
        return len(_queue)


def queue_snapshot() -> Dict[str, Any]:
    """队列概况，供 `/api/analysis/queue` 与日志使用。"""
    with _lock:
        pending_ids = [item[0] for item in _queue]
        total = _seq_counter
        worker = _worker
    return {
        "running": _current_id,
        "pending": pending_ids,
        "pendingCount": len(pending_ids),
        "workerAlive": bool(worker is not None and worker.is_alive()),
        "enqueuedTotal": total,
    }


def queue_position_of(analysis_id: str) -> Optional[int]:
    """某任务前面还有几个在排队（不含正在执行的那个）；不在队列里返回 None。"""
    with _lock:
        for index, item in enumerate(_queue):
            if item[0] == str(analysis_id):
                return index
    return None


def _worker_loop() -> None:
    """唯一的 worker 线程：串行地取任务、执行、再取下一个。"""
    global _current_id
    while not _shutdown.is_set():
        try:
            analysis_id, payload = _queue.popleft()
        except IndexError:
            # 队列空：等唤醒信号（退出信号也会 set 它）
            _wakeup.wait(timeout=1.0)
            _wakeup.clear()
            continue

        _current_id = analysis_id
        try:
            log.info("开始执行队列任务: %s（队列中还有 %s 个待执行）", analysis_id, pending_count())
            run_full_analysis(analysis_id=analysis_id, **payload)
        except Exception as e:                                        # noqa: BLE001
            # run_full_analysis 自己会把记录标成 failed 并吞掉异常，这里只兜底
            log.error("队列任务 %s 执行失败: %s", analysis_id, e, exc_info=True)
        finally:
            _current_id = None


def requeue_pending_on_startup() -> Dict[str, int]:
    """清理上一进程遗留的未完成任务（队列不跨重启）。

    * `queued`：入队后进程就没了，任务不可能再执行 -> 标 `failed`
    * `processing`：说明推理中途被打断（进程被杀）。按原图是否还在分别处理：
        - 原图还在 -> 重新入队，让用户不必手动重传
        - 原图已丢 -> 标 `failed`
    返回 {'queued_failed': n, 'processing_requeued': n, 'processing_failed': n}
    """
    result = {'queued_failed': 0, 'processing_requeued': 0, 'processing_failed': 0}
    # 入队需要的信息在 session 内就取出来（commit 后 ORM 属性会过期，
    # 离开 session 再读会抛 DetachedInstanceError）
    to_requeue: List[Dict[str, Any]] = []
    try:
        with Session(sync_engine) as session:
            queued = session.exec(select(Analysis).where(Analysis.status == "queued")).all()
            for record in queued:
                record.status = "failed"
                record.updated_at = datetime.utcnow()
                session.add(record)
            result['queued_failed'] = len(queued)
            if queued:
                session.commit()
                log.warning("发现 %s 条 queued 记录（队列不跨重启），已标记为 failed", len(queued))

            stuck = session.exec(select(Analysis).where(Analysis.status == "processing")).all()
            for record in stuck:
                if record.original_file_path and os.path.exists(record.original_file_path):
                    # 原图还在：重新排队，交给 worker 接着跑
                    record.status = "queued"
                    record.started_at = None
                    record.finished_at = None
                    session.add(record)
                    to_requeue.append({
                        "analysis_id": str(record.analysis_id),
                        "original_file_path": record.original_file_path,
                        "user_id": str(record.user_id),
                        "task_type": record.task_type or "stem",
                    })
                else:
                    # 原图已不在，重跑也没有意义
                    record.status = "failed"
                    record.updated_at = datetime.utcnow()
                    session.add(record)
                    result['processing_failed'] += 1
            session.commit()
            if stuck:
                log.warning(
                    "发现 %s 条 processing 记录（上次推理被打断）：%s 条重新入队，%s 条因原图丢失标记为 failed",
                    len(stuck), len(to_requeue), result['processing_failed'],
                )
    except Exception as e:                                            # noqa: BLE001
        log.warning("清理遗留任务失败: %s", e)
        return result

    for item in to_requeue:
        # 逐条单独处理：某一条入队失败不能影响其它记录，也不能被上面的 try 吞掉计数
        try:
            enqueue_analysis(
                item["analysis_id"],
                {
                    "original_file_path": item["original_file_path"],
                    "user_id": item["user_id"],
                    "original_filename": os.path.basename(item["original_file_path"]),
                    "task_type": item["task_type"],
                },
            )
            result['processing_requeued'] += 1
        except Exception as e:                                            # noqa: BLE001
            log.error("重新入队失败 %s: %s", item["analysis_id"], e)
            # 入队失败的记录不能留在 queued（会永远等不到结果），标记为失败
            try:
                with Session(sync_engine) as session:
                    failed = session.exec(
                        select(Analysis).where(Analysis.analysis_id == item["analysis_id"])
                    ).one_or_none()
                    if failed:
                        failed.status = "failed"
                        failed.updated_at = datetime.utcnow()
                        session.add(failed)
                        session.commit()
            except Exception as inner:                                    # noqa: BLE001
                log.warning("回滚 %s 状态失败: %s", item["analysis_id"], inner)

    return result


def _run_full_analysis(**kwargs):
    """延迟导入推理模块，避免应用启动时就把 torch 拉起来。"""
    from app.features.analysis.service import run_full_analysis as _run

    return _run(**kwargs)


# worker 线程里调用的入口；单独抽成模块级名字，便于测试替换
run_full_analysis = _run_full_analysis
