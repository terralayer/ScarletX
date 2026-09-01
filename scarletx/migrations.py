from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection


PERFORMANCE_INDEXES = (
    (
        "native_usenet_jobs",
        "ix_native_usenet_jobs_status_created_at",
        "status, created_at",
    ),
    (
        "native_usenet_jobs",
        "ix_native_usenet_jobs_status_updated_at",
        "status, updated_at",
    ),
    (
        "tracked_downloads",
        "ix_tracked_downloads_status_created_at",
        "status, created_at",
    ),
    (
        "tracked_downloads",
        "ix_tracked_downloads_status_last_checked_at",
        "status, last_checked_at",
    ),
    (
        "background_jobs",
        "ix_background_jobs_status_kind_created_at",
        "status, kind, created_at",
    ),
    (
        "history",
        "ix_history_event_type_created_at",
        "event_type, created_at",
    ),
)


def ensure_performance_indexes(connection: Connection) -> None:
    """Create the 0.3.10 SQLite worker indexes without rewriting user data."""
    if connection.dialect.name != "sqlite":
        return

    tables = set(inspect(connection).get_table_names())
    for table, index_name, columns in PERFORMANCE_INDEXES:
        if table not in tables:
            continue
        connection.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns})"
        )
