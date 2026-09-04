from __future__ import annotations

from sqlalchemy import inspect, text
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


def performance_index_migration_required(connection: Connection) -> bool:
    """Return whether this SQLite database still needs any PR-2 worker index."""
    if connection.dialect.name != "sqlite":
        return False

    tables = set(inspect(connection).get_table_names())
    required = {
        index_name
        for table, index_name, _columns in PERFORMANCE_INDEXES
        if table in tables
    }
    existing = {
        str(row[0])
        for row in connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        )
        if row[0]
    }
    return not required.issubset(existing)


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


def ensure_file_scan_state_table(connection: Connection) -> None:
    """Create PR-5 scanner state for databases upgraded in place."""
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS file_scan_states ("
        "path VARCHAR(3000) NOT NULL PRIMARY KEY, "
        "size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, "
        "scanned_at DATETIME NOT NULL)"
    )
