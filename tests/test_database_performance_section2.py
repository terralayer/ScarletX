from __future__ import annotations

from sqlalchemy import create_engine, text


LIBRARY_INDEXES = {
    "ix_scenes_type_release_id": (
        "SELECT id FROM scenes WHERE content_type='scene' "
        "ORDER BY release_date DESC, id DESC LIMIT 100"
    ),
    "ix_scenes_studio_type": (
        "SELECT count(id) FROM scenes WHERE studio_id=1 AND content_type='scene'"
    ),
    "ix_performers_library_name": (
        "SELECT id FROM performers WHERE is_library=1 ORDER BY name, id LIMIT 100"
    ),
    "ix_studios_library_name": (
        "SELECT id FROM studios WHERE is_library=1 ORDER BY name, id LIMIT 100"
    ),
    "ix_media_files_scene_id": (
        "SELECT id FROM media_files WHERE scene_id=1 ORDER BY id LIMIT 1"
    ),
}


def _legacy_library_schema(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE scenes ("
            "id INTEGER PRIMARY KEY, content_type TEXT NOT NULL, release_date DATE, "
            "studio_id INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE performers (id INTEGER PRIMARY KEY, is_library BOOLEAN NOT NULL, name TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE studios (id INTEGER PRIMARY KEY, is_library BOOLEAN NOT NULL, name TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE media_files (id INTEGER PRIMARY KEY, scene_id INTEGER NOT NULL)"
        )


def _index_names(engine) -> set[str]:
    with engine.connect() as connection:
        return {
            str(row[0])
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'")
            )
        }


def test_upgrade_adds_library_hot_path_indexes_idempotently(tmp_path):
    from scarletx.migrations import ensure_performance_indexes, performance_index_migration_required

    engine = create_engine(f"sqlite:///{tmp_path / 'library-indexes.db'}")
    _legacy_library_schema(engine)

    with engine.connect() as connection:
        assert performance_index_migration_required(connection) is True

    with engine.begin() as connection:
        ensure_performance_indexes(connection)
        ensure_performance_indexes(connection)

    assert LIBRARY_INDEXES.keys() <= _index_names(engine)
    with engine.connect() as connection:
        assert performance_index_migration_required(connection) is False


def test_library_hot_path_queries_use_declared_indexes(tmp_path):
    from scarletx.migrations import ensure_performance_indexes

    engine = create_engine(f"sqlite:///{tmp_path / 'library-plans.db'}")
    _legacy_library_schema(engine)
    with engine.begin() as connection:
        ensure_performance_indexes(connection)
        for index_name, query in LIBRARY_INDEXES.items():
            plan = " ".join(
                str(row[3])
                for row in connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {query}")
            )
            assert index_name in plan, (index_name, plan)
