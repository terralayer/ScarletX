from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.media_library import _match_local_scene, _norm
from scarletx.media_watch import _scene_candidates
from scarletx.models import LibraryItemConfig, MediaFile, QualityProfile, Scene
from scarletx.rss import _match_context
from scarletx.wanted import cutoff_unmet, missing_items


def populated_session(scene_count: int = 200):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        profile = QualityProfile(
            name="Default",
            content_type="scene",
            cutoff_quality="1080p",
            is_default=True,
        )
        db.add(profile)
        db.flush()
        scenes = [
            Scene(
                tpdb_id=f"scene-{index}",
                title=f"Scene {index:04d}",
                content_type="scene",
                release_date=date(2026, 1, 1),
                monitored=True,
            )
            for index in range(scene_count)
        ]
        db.add_all(scenes)
        db.flush()
        db.add_all(
            LibraryItemConfig(scene_id=scene.id, quality_profile_id=profile.id)
            for scene in scenes
        )
        db.add_all(
            MediaFile(
                scene_id=scene.id,
                path=f"/media/{scene.id}.mp4",
                size_bytes=1,
                quality="720p",
            )
            for scene in scenes[::2]
        )
        db.commit()
    return engine, session_factory


def count_queries(engine):
    state = {"count": 0, "statements": []}

    def increment(_connection, _cursor, statement, *_args):
        state["count"] += 1
        state["statements"].append(statement)

    event.listen(engine, "before_cursor_execute", increment)
    return state


def test_missing_items_uses_one_bounded_query():
    engine, session_factory = populated_session()
    queries = count_queries(engine)

    with session_factory() as db:
        rows = missing_items(db, limit=50)

    assert len(rows) == 50
    assert queries["count"] == 1


def test_cutoff_unmet_uses_bulk_queries():
    engine, session_factory = populated_session()
    queries = count_queries(engine)

    with session_factory() as db:
        rows = cutoff_unmet(db, limit=50)

    assert len(rows) == 50
    assert queries["count"] <= 5
    assert not any("scene_id IN" in statement for statement in queries["statements"])


def test_rss_context_does_not_expand_scene_ids_into_sql_parameters():
    engine, session_factory = populated_session()
    queries = count_queries(engine)

    with session_factory() as db:
        scenes, profiles, current = _match_context(db)

    assert len(scenes) == 200
    assert len(profiles) == 200
    assert len(current) == 100
    assert not any("scene_id IN" in statement for statement in queries["statements"])


def test_watcher_matches_titles_when_apostrophes_are_removed_from_filename():
    _engine, session_factory = populated_session(scene_count=0)
    with session_factory() as db:
        scene = Scene(tpdb_id="apostrophe", title="Don't Go", content_type="scene", monitored=True)
        db.add(scene)
        db.commit()

        path = Path("Dont.Go.1080p.mp4")
        candidates = _scene_candidates(db, path)

    assert _norm("Don't Go") == "dont go"
    assert _match_local_scene(path, candidates).id == scene.id
