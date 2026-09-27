"""数据库日志开关（DB_ECHO）回归测试。

此前 `app/database/session.py` 把 echo 硬编码为 True，导致每条 ORM 语句
都写进 uvicorn 的 stdout，访问日志被淹没；现在改为由 `.env` 的 `DB_ECHO`
控制且默认关闭。
"""
import unittest


class DbEchoConfigTests(unittest.TestCase):
    def test_db_echo_defaults_to_false(self):
        from app.core.config import Settings

        # 默认值来自字段声明（.env 缺失或未写该项时生效）
        self.assertIs(Settings.model_fields["DB_ECHO"].default, False)

    def test_db_echo_is_boolean_and_matches_engine(self):
        from app.core.config import settings
        from app.database.session import engine

        self.assertIsInstance(settings.DB_ECHO, bool)
        self.assertIs(engine.echo, settings.DB_ECHO)

    def test_sync_engines_do_not_enable_echo(self):
        # 后台任务与 Excel 导出的同步引擎始终 echo=False
        from app.services.analysis_service import sync_engine

        self.assertFalse(sync_engine.echo)


if __name__ == "__main__":
    unittest.main()
