"""分析队列（串行执行）回归测试。

背景：原来用 FastAPI `BackgroundTasks` 派发推理，**多个请求各自的后台任务会并发执行**。
5 张图同时起步 = 5 个子进程 + 5 份模型权重，普通机器直接卡死。
现在改为单 worker 线程 + FIFO 队列，这里验证"同一时刻只有一个任务在跑"。
"""
import threading
import time
import unittest


class QueueSerializationTests(unittest.TestCase):
    """把真正跑推理的函数换成记录器，观察执行顺序与重叠情况。"""

    def setUp(self):
        from app.features.analysis import queue as analysis_queue

        self.queue = analysis_queue
        # 清空共享状态（模块级单例，测试间必须隔离）
        self.queue._queue.clear()
        self.queue._shutdown.clear()
        self.queue._wakeup.clear()
        self.queue._worker = None
        self.queue._seq_counter = 0
        self.queue._current_id = None

        self.events = []
        self._running = 0
        self.concurrent_peak = 0
        self._lock = threading.Lock()
        self._original_runner = self.queue.run_full_analysis
        self.queue.run_full_analysis = self._fake_runner

    def tearDown(self):
        self.queue.stop_worker(timeout=2)
        self.queue.run_full_analysis = self._original_runner
        self.queue._queue.clear()

    def _fake_runner(self, analysis_id, **payload):
        with self._lock:
            self._running += 1
            self.concurrent_peak = max(self.concurrent_peak, self._running)
            self.events.append(('start', analysis_id))
        try:
            time.sleep(0.03)                     # 模拟一次推理
        finally:
            with self._lock:
                self.events.append(('end', analysis_id))
                self._running -= 1

    def _wait_until_empty(self, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.queue.pending_count() == 0 and self.queue._current_id is None:
                return True
            time.sleep(0.01)
        return False

    def test_jobs_run_one_at_a_time_and_in_order(self):
        self.queue.start_worker()
        for i in range(3):
            self.queue.enqueue_analysis(f'job-{i}', {})

        self.assertTrue(self._wait_until_empty(), '队列应在超时前跑空')
        self.queue.stop_worker(timeout=2)

        self.assertEqual(self.concurrent_peak, 1, '同一时刻只能有一个推理在执行')
        order = [name for kind, name in self.events if kind == 'start']
        self.assertEqual(order, ['job-0', 'job-1', 'job-2'], '必须按入队顺序执行')
        # 严格交替的 开始/结束 序列 == 没有交错执行
        pairs = list(zip(self.events[::2], self.events[1::2]))
        for start, end in pairs:
            with self.subTest(job=start[1]):
                self.assertEqual(start[0], 'start')
                self.assertEqual(end[0], 'end')
                self.assertEqual(start[1], end[1])

    def test_worker_start_is_idempotent(self):
        self.queue.start_worker()
        first = self.queue._worker
        self.queue.start_worker()
        self.assertIs(self.queue._worker, first, '重复启动不应产生第二个 worker 线程')
        self.queue.stop_worker(timeout=2)

    def test_snapshot_reports_pending_and_worker(self):
        # 不启动 worker，只入队：任务应老老实实排在队列里
        self.queue.enqueue_analysis('a', {})
        self.queue.enqueue_analysis('b', {})

        snapshot = self.queue.queue_snapshot()

        self.assertEqual(snapshot['pendingCount'], 2)
        self.assertEqual(snapshot['pending'], ['a', 'b'])
        self.assertEqual(snapshot['enqueuedTotal'], 2)
        self.assertIsNone(snapshot['running'])
        self.assertFalse(snapshot['workerAlive'], '未启动时为 False')
        self.queue._queue.clear()

    def test_queue_position_tracks_order(self):
        self.queue.enqueue_analysis('first', {})
        self.queue.enqueue_analysis('second', {})

        self.assertEqual(self.queue.queue_position_of('first'), 0)
        self.assertEqual(self.queue.queue_position_of('second'), 1)
        self.assertIsNone(self.queue.queue_position_of('nope'))
        self.queue._queue.clear()

    def test_failing_job_does_not_block_the_queue(self):
        """一次推理失败不能把队列卡死（run_full_analysis 内部已把记录标 failed）。"""
        calls = []

        def flaky(analysis_id, **payload):
            calls.append(analysis_id)
            if analysis_id == 'boom':
                raise RuntimeError('推理炸了')

        self.queue.run_full_analysis = flaky
        self.queue.start_worker()
        self.queue.enqueue_analysis('boom', {})
        self.queue.enqueue_analysis('after-boom', {})

        self.assertTrue(self._wait_until_empty())
        self.queue.stop_worker(timeout=2)

        self.assertEqual(calls, ['boom', 'after-boom'], '失败任务后面的任务仍要执行')

    def test_worker_survives_no_work(self):
        """没有任务时 worker 不应忙转/退出，来活了还能接着处理。"""
        self.queue.start_worker()
        time.sleep(0.15)
        self.assertTrue(self.queue._worker.is_alive(), '空闲时 worker 应继续存活')

        self.queue.enqueue_analysis('later', {})
        self.assertTrue(self._wait_until_empty())
        self.queue.stop_worker(timeout=2)

        self.assertEqual([name for kind, name in self.events if kind == 'start'], ['later'])

    def test_stop_worker_then_enqueue_does_not_run(self):
        """停止后入队的任务不会被执行（进程退出后的残留由启动清理负责）。"""
        self.queue.start_worker()
        self.queue.stop_worker(timeout=2)
        self.queue.enqueue_analysis('orphan', {})
        time.sleep(0.15)

        self.assertEqual([n for k, n in self.events if k == 'start'], [])
        self.assertEqual(self.queue.pending_count(), 1)


if __name__ == '__main__':
    unittest.main()
