from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from .watchdog import ensure_watchdog_model_columns


PERFORMANCE_INDEXES = (
    ("history", "ix_history_scene_event_created", "scene_id, event_type, created_at"),
    ("tracked_downloads", "ix_tracked_downloads_scene_created_id", "scene_id, created_at, id"),
    ("scenes", "ix_scenes_wanted_order", "content_type, monitored, release_date, title, id"),
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
    (
        "scenes",
        "ix_scenes_type_release_id",
        "content_type, release_date DESC, id DESC",
    ),
    (
        "scenes",
        "ix_scenes_studio_type",
        "studio_id, content_type",
    ),
    (
        "performers",
        "ix_performers_library_name",
        "is_library, name",
    ),
    (
        "studios",
        "ix_studios_library_name",
        "is_library, name",
    ),
    (
        "media_files",
        "ix_media_files_scene_id",
        "scene_id",
    ),
)


def ensure_native_watchdog_columns(connection: Connection) -> None:
    """Add durable watchdog state to an existing native queue in place."""

    ensure_watchdog_model_columns()
    if connection.dialect.name != "sqlite":
        return
    inspector = inspect(connection)
    if "native_usenet_jobs" not in set(inspector.get_table_names()):
        return

    existing = {
        str(column["name"])
        for column in inspector.get_columns("native_usenet_jobs")
    }
    additions = (
        (
            "watchdog_retries",
            "ALTER TABLE native_usenet_jobs "
            "ADD COLUMN watchdog_retries INTEGER NOT NULL DEFAULT 0",
        ),
        (
            "retry_after",
            "ALTER TABLE native_usenet_jobs ADD COLUMN retry_after DATETIME",
        ),
        (
            "quarantined",
            "ALTER TABLE native_usenet_jobs "
            "ADD COLUMN quarantined BOOLEAN NOT NULL DEFAULT 0",
        ),
    )
    for column_name, statement in additions:
        if column_name not in existing:
            connection.exec_driver_sql(statement)
            existing.add(column_name)


def _available_performance_indexes(connection: Connection):
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    columns_by_table = {}
    for table, name, columns in PERFORMANCE_INDEXES:
        if table not in tables:
            continue
        if table not in columns_by_table:
            columns_by_table[table] = {column["name"] for column in inspector.get_columns(table)}
        required_columns = {part.strip().split()[0] for part in columns.split(",")}
        # Partial/older schemas may not yet have all columns. Recheck after they are added.
        if required_columns <= columns_by_table[table]:
            yield table, name, columns


def performance_index_migration_required(connection: Connection) -> bool:
    """Return whether this SQLite database still needs a performance index."""
    if connection.dialect.name != "sqlite":
        return False

    required = {index_name for _table, index_name, _columns in _available_performance_indexes(connection)}
    existing = {
        str(row[0])
        for row in connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        )
        if row[0]
    }
    return not required.issubset(existing)


def ensure_performance_indexes(connection: Connection) -> None:
    """Create SQLite worker/library indexes and small upgrade columns safely."""
    if connection.dialect.name != "sqlite":
        return

    ensure_native_watchdog_columns(connection)
    for table, index_name, columns in _available_performance_indexes(connection):
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
