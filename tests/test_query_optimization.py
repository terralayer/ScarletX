from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import MediaFile, Performer, Scene, Studio


PERFORMANCE_INDEXES = {
    "ix_native_usenet_jobs_status_created_at",
    "ix_native_usenet_jobs_status_updated_at",
    "ix_tracked_downloads_status_created_at",
    "ix_tracked_downloads_status_last_checked_at",
    "ix_background_jobs_status_kind_created_at",
    "ix_history_event_type_created_at",
}

INDEX_PLAN_QUERIES = {
    "ix_native_usenet_jobs_status_created_at": (
        "SELECT id FROM native_usenet_jobs "
        "WHERE status='queued' ORDER BY created_at ASC LIMIT 20"
    ),
    "ix_native_usenet_jobs_status_updated_at": (
        "SELECT id FROM native_usenet_jobs "
        "WHERE status='failed' ORDER BY updated_at DESC LIMIT 20"
    ),
    "ix_tracked_downloads_status_created_at": (
        "SELECT id FROM tracked_downloads "
        "WHERE status='queued' ORDER BY created_at ASC LIMIT 20"
    ),
    "ix_tracked_downloads_status_last_checked_at": (
        "SELECT id FROM tracked_downloads "
        "WHERE status='downloading' ORDER BY last_checked_at ASC LIMIT 20"
    ),
    "ix_background_jobs_status_kind_created_at": (
        "SELECT id FROM background_jobs "
        "WHERE status='queued' AND kind='media_library_scan' "
        "ORDER BY created_at DESC LIMIT 20"
    ),
    "ix_history_event_type_created_at": (
        "SELECT id FROM history "
        "WHERE event_type='download_failed' ORDER BY created_at DESC LIMIT 20"
    ),
}


@contextmanager
def _select_counter(engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record_select(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_select)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record_select)


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'query-optimization.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed_scenes(session_factory, tmp_path: Path, count: int) -> None:
    started = datetime(2026, 1, 1, tzinfo=UTC)
    with session_factory() as db:
        studio = Studio(
            tpdb_id="studio-query-test",
            name="Query Test Studio",
            is_library=True,
        )
        performers = [
            Performer(
                tpdb_id=f"performer-query-{index}",
                name=f"Query Performer {index}",
                image_url=f"https://example.invalid/{index}.jpg",
                aliases=f"Alias {index}",
                bio="detail-only performer biography",
                is_library=True,
            )
            for index in range(3)
        ]
        db.add_all([studio, *performers])
        db.flush()

        scenes = []
        for index in range(count):
            scene = Scene(
                tpdb_id=f"scene-query-{index}",
                title=f"Query Scene {index:03d}",
                content_type="scene",
                description="detail-only scene description",
                image_url=f"https://example.invalid/scene-{index}.jpg",
                studio=studio,
                imported_at=started + timedelta(seconds=index),
            )
            scene.performers.extend((performers[index % 3], performers[(index + 1) % 3]))
            scenes.append(scene)
        db.add_all(scenes)
        db.flush()
        for scene in scenes[::2]:
            db.add(
                MediaFile(
                    scene_id=scene.id,
                    path=str(tmp_path / f"scene-{scene.id}.mp4"),
                    size_bytes=1_000_000,
                )
            )
        db.commit()


def _create_039_worker_schema(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE native_usenet_jobs ("
            "id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE tracked_downloads ("
            "id INTEGER PRIMARY KEY, status TEXT NOT NULL, created_at DATETIME NOT NULL, "
            "last_checked_at DATETIME)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE background_jobs ("
            "id INTEGER PRIMARY KEY, status TEXT NOT NULL, kind TEXT NOT NULL, "
            "created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE history ("
            "id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO native_usenet_jobs VALUES "
            "('one','queued','2026-01-01','2026-01-01')"
        )
        connection.exec_driver_sql(
            "INSERT INTO tracked_downloads VALUES "
            "(1,'downloading','2026-01-01','2026-01-01')"
        )
        connection.exec_driver_sql(
            "INSERT INTO background_jobs VALUES "
            "(1,'queued','media_library_scan','2026-01-01')"
        )
        connection.exec_driver_sql(
            "INSERT INTO history VALUES (1,'download_failed','2026-01-01')"
        )


def _index_names(engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'")
        )
        return {str(row[0]) for row in rows}


def test_039_database_upgrade_adds_worker_indexes_without_data_loss(tmp_path):
    from scarletx.migrations import ensure_performance_indexes

    engine = create_engine(f"sqlite:///{tmp_path / 'upgrade-039.db'}")
    _create_039_worker_schema(engine)

    with engine.begin() as connection:
        ensure_performance_indexes(connection)
        ensure_performance_indexes(connection)

    assert PERFORMANCE_INDEXES <= _index_names(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM native_usenet_jobs")) == 1
        assert connection.scalar(text("SELECT count(*) FROM tracked_downloads")) == 1
        assert connection.scalar(text("SELECT count(*) FROM background_jobs")) == 1
        assert connection.scalar(text("SELECT count(*) FROM history")) == 1


@pytest.mark.parametrize("index_name,query", INDEX_PLAN_QUERIES.items())
def test_worker_query_uses_declared_composite_index(tmp_path, index_name: str, query: str):
    from scarletx.migrations import ensure_performance_indexes

    engine = create_engine(f"sqlite:///{tmp_path / 'plans.db'}")
    _create_039_worker_schema(engine)
    with engine.begin() as connection:
        ensure_performance_indexes(connection)
        detail = " ".join(
            str(row[3]) for row in connection.exec_driver_sql(f"EXPLAIN QUERY PLAN {query}")
        )

    assert index_name in detail


@pytest.mark.parametrize("count", [1, 100])
def test_scene_list_query_count_is_constant(tmp_path, count: int):
    from scarletx.main import library_scene_page

    engine, Session = _session_factory(tmp_path)
    _seed_scenes(Session, tmp_path, count)

    with Session() as db, _select_counter(engine) as statements:
        payload = library_scene_page(
            limit=min(count, 100),
            offset=0,
            cursor=None,
            q=None,
            db=db,
        )

    assert len(payload["items"]) == count
    assert len(statements) <= 3


def test_scene_list_uses_summary_projection(tmp_path):
    from scarletx.main import library_scene_page

    engine, Session = _session_factory(tmp_path)
    _seed_scenes(Session, tmp_path, 2)

    with Session() as db, _select_counter(engine) as statements:
        payload = library_scene_page(limit=2, offset=0, cursor=None, q=None, db=db)

    data_query = next(statement for statement in statements if "ORDER BY scenes.imported_at" in statement)
    assert "scenes.description" not in data_query
    assert set(payload["items"][0]) == {
        "id",
        "tpdb_id",
        "title",
        "release_date",
        "image_url",
        "monitored",
        "studio",
        "studio_id",
        "performers",
        "has_file",
    }


def test_performer_list_uses_summary_projection(tmp_path):
    from scarletx.main import performers_library_page

    engine, Session = _session_factory(tmp_path)
    _seed_scenes(Session, tmp_path, 1)

    with Session() as db, _select_counter(engine) as statements:
        payload = performers_library_page(
            limit=10,
            offset=0,
            cursor=None,
            q=None,
            db=db,
        )

    data_query = next(statement for statement in statements if "ORDER BY performers.name" in statement)
    assert "performers.bio" not in data_query
    assert set(payload["items"][0]) == {
        "id",
        "tpdb_id",
        "name",
        "image_url",
        "aliases",
        "monitored",
    }


def test_studio_list_uses_summary_projection(tmp_path):
    from scarletx.main import studios_library_page

    engine, Session = _session_factory(tmp_path)
    _seed_scenes(Session, tmp_path, 1)

    with Session() as db, _select_counter(engine) as statements:
        payload = studios_library_page(
            limit=10,
            offset=0,
            cursor=None,
            q=None,
            db=db,
        )

    data_query = next(statement for statement in statements if "ORDER BY studios.name" in statement)
    assert "studios.description" not in data_query
    assert "studios.url" not in data_query
    assert set(payload["items"][0]) == {
        "id",
        "tpdb_id",
        "name",
        "image_url",
        "monitored",
    }
