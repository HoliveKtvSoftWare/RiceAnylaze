"""后端重启后的遗留任务清理（`requeue_pending_on_startup`）回归测试。

背景：任务队列在进程内存里，后端重启会丢失队列。库里因此可能残留：
  * `queued`  —— 任务不可能再执行
  * `processing` —— 推理被打断（进程被杀），其中原图还在的应该重新排队
不处理的话这些记录会永远停在"排队中/处理中"，前端会一直轮询等不到结果。
"""
import os
import shutil
import unittest
import uuid

# 固定的测试用户 ID（SQLite 下 UUID 列要求真正的 uuid 对象，不能传字符串）
TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def _uuid_of(label: str) -> uuid.UUID:
    """把可读标签映射成稳定的 UUID，便于断言。"""
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"rice-test-{label}")


class StuckTaskCleanupTests(unittest.TestCase):
    TEST_TMP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp")

    def setUp(self):
        from sqlmodel import Session, SQLModel, create_engine

        # 必须先把 users 模型导进来，否则 analyses 的外键找不到目标表
        from app.models.user import UserTable  # noqa: F401
        from app.models.analysis import Analysis  # noqa: F401
        from app.models.batch import UploadBatch  # noqa: F401

        os.makedirs(self.TEST_TMP_ROOT, exist_ok=True)
        self.tmp = os.path.join(self.TEST_TMP_ROOT, self._testMethodName)
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.makedirs(self.tmp)
        self.addCleanup(shutil.rmtree, self.tmp, True)

        # 用独立的 SQLite 库跑，避免碰真实 PostgreSQL 数据
        self.engine = create_engine(f"sqlite:///{os.path.join(self.tmp, 'test.db')}", echo=False)
        SQLModel.metadata.create_all(self.engine)

        from app.services import analysis_queue

        self.queue = analysis_queue
        self._original_engine = analysis_queue.sync_engine
        analysis_queue.sync_engine = self.engine
        self.addCleanup(self._restore_engine)

        # 队列本身也重置，并屏蔽真正的推理
        self.queue._queue.clear()
        self.queue._shutdown.clear()
        self.queue._wakeup.clear()
        self.queue._worker = None
        self.queue._seq_counter = 0
        self.queue._current_id = None
        self._original_runner = self.queue.run_full_analysis
        self.queue.run_full_analysis = lambda analysis_id, **payload: None
        self.addCleanup(self._restore_runner)
        self.addCleanup(self._reset_queue)

    def _reset_queue(self):
        self.queue.stop_worker(timeout=2)
        self.queue._queue.clear()

    def _restore_runner(self):
        self.queue.run_full_analysis = self._original_runner

    def _restore_engine(self):
        self.queue.sync_engine = self._original_engine

    def _add_record(self, label, status, has_file):
        from sqlmodel import Session

        from app.models.analysis import Analysis

        path = os.path.join(self.tmp, f"{label}.tif")
        if has_file:
            with open(path, "wb") as f:
                f.write(b"fake image")
        with Session(self.engine) as session:
            session.add(Analysis(
                analysis_id=_uuid_of(label),
                status=status,
                task_type="leaf_our",
                original_file_path=path,
                user_id=TEST_USER_ID,
            ))
            session.commit()

    def _status_of(self, label):
        from sqlmodel import Session, select

        from app.models.analysis import Analysis

        with Session(self.engine) as session:
            record = session.exec(
                select(Analysis).where(Analysis.analysis_id == _uuid_of(label))
            ).one()
            return record.status

    def test_queued_record_is_marked_failed(self):
        self._add_record("q1", "queued", has_file=True)

        result = self.queue.requeue_pending_on_startup()

        self.assertEqual(result["queued_failed"], 1)
        self.assertEqual(self._status_of("q1"), "failed")

    def test_interrupted_job_with_file_is_requeued(self):
        """推理被打断但原图还在 -> 重新入队（前端不必手动重传）。"""
        self._add_record("p1", "processing", has_file=True)

        result = self.queue.requeue_pending_on_startup()

        self.assertEqual(result["processing_requeued"], 1)
        self.assertEqual(self._status_of("p1"), "queued")
        self.assertEqual(self.queue.pending_count(), 1, "应真的排入队列")
        # started_at / finished_at 要清掉，否则统计里会出现一段假的超长耗时
        from sqlmodel import Session, select

        from app.models.analysis import Analysis

        with Session(self.engine) as session:
            record = session.exec(
                select(Analysis).where(Analysis.analysis_id == _uuid_of("p1"))
            ).one()
            self.assertIsNone(record.started_at)
            self.assertIsNone(record.finished_at)

    def test_interrupted_job_without_file_is_marked_failed(self):
        """原图已丢失（被清理过）-> 重跑没有意义，标失败。"""
        self._add_record("p2", "processing", has_file=False)

        result = self.queue.requeue_pending_on_startup()

        self.assertEqual(result["processing_failed"], 1)
        self.assertEqual(result["processing_requeued"], 0)
        self.assertEqual(self._status_of("p2"), "failed")
        self.assertEqual(self.queue.pending_count(), 0)

    def test_completed_records_are_untouched(self):
        self._add_record("c1", "completed", has_file=True)

        result = self.queue.requeue_pending_on_startup()

        self.assertEqual(result, {"queued_failed": 0, "processing_requeued": 0, "processing_failed": 0})
        self.assertEqual(self._status_of("c1"), "completed")

    def test_mixed_batch(self):
        self._add_record("m1", "queued", has_file=True)
        self._add_record("m2", "processing", has_file=True)
        self._add_record("m3", "processing", has_file=False)
        self._add_record("m4", "completed", has_file=True)

        result = self.queue.requeue_pending_on_startup()

        self.assertEqual(result["queued_failed"], 1)
        self.assertEqual(result["processing_requeued"], 1)
        self.assertEqual(result["processing_failed"], 1)
        self.assertEqual(self._status_of("m1"), "failed")
        self.assertEqual(self._status_of("m2"), "queued")
        self.assertEqual(self._status_of("m3"), "failed")
        self.assertEqual(self._status_of("m4"), "completed")
        self.assertEqual(self.queue.pending_count(), 1)


if __name__ == "__main__":
    unittest.main()
