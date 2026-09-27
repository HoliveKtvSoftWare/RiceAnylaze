"""Existing non-destructive compatibility migrations, run only at startup."""

import logging

from sqlalchemy import inspect, text

log = logging.getLogger(__name__)

_LIGHT_MIGRATIONS = {
    "analyses": [
        ("started_at", "TIMESTAMP WITHOUT TIME ZONE"),
        ("finished_at", "TIMESTAMP WITHOUT TIME ZONE"),
        ("model_used", "VARCHAR"),
        ("error_message", "VARCHAR"),
    ],
    "upload_batches": [
        ("name", "VARCHAR"),
    ],
}


async def apply_light_migrations(conn) -> None:
    for table, columns in _LIGHT_MIGRATIONS.items():
        exists = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table))
        if not exists:
            continue
        existing = await conn.run_sync(
            lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns(table)}
        )
        for column, ddl_type in columns:
            if column not in existing:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                log.info("数据库兼容迁移：%s 添加列 %s", table, column)
