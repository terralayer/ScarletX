from __future__ import annotations

import inspect
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.config import Settings
from scarletx.db import Base
from scarletx.library_management import import_specific_media_file
from scarletx.models import History, MediaFile, RootFolder, Scene
from scarletx.schemas import GeneralSettingsWrite
from scarletx import list_queries, media_library


ROOT = Path(__file__).resolve().parents[1]


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard-dedup.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_downloaded_scene_page_filters_metadata_only_scenes(tmp_path):
    assert "downloaded_only" in inspect.signature(list_queries.scene_summary_page).parameters

    engine, factory = _session_factory(tmp_path)
    with factory() as db:
        downloaded = Scene(tpdb_id="downloaded", title="Downloaded", content_type="scene")
        wanted = Scene(tpdb_id="wanted", title="Wanted", content_type="scene", monitored=True)
        db.add_all([downloaded, wanted])
        db.flush()
        db.add(MediaFile(scene_id=downloaded.id, path=str(tmp_path / "downloaded.mp4"), size_bytes=5))
        db.commit()

        page = list_queries.scene_summary_page(db, limit=10, downloaded_only=True)

        assert page["total"] == 1
        assert [item["id"] for item in page["items"]] == [downloaded.id]
        assert page["items"][0]["has_file"] is True
    engine.dispose()


def test_dashboard_uses_downloaded_scene_count_and_recent_page():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    routes = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")

    assert "/api/library/scenes/page?limit=8&downloaded_only=true" in source
    assert "sys.library?.downloaded_scene" in source
    assert '"downloaded_scene"' in routes


def test_exact_duplicate_import_is_removed_but_same_size_different_content_is_kept(tmp_path):
    engine, factory = _session_factory(tmp_path)
    media_root = tmp_path / "media"
    media_root.mkdir()
    first_source = tmp_path / "first.mp4"
    duplicate_source = tmp_path / "duplicate.mp4"
    different_source = tmp_path / "different.mp4"
    first_source.write_bytes(b"same-video-bytes")
    duplicate_source.write_bytes(b"same-video-bytes")
    different_source.write_bytes(b"other-video-data")
    assert different_source.stat().st_size == first_source.stat().st_size

    settings = Settings(
        scene_naming_template="{Title}",
        import_mode="copy",
        minimum_free_space_gb=0,
    )

    with factory() as db:
        scene = Scene(tpdb_id="duplicate-scene", title="Duplicate Scene", content_type="scene")
        db.add(scene)
        db.flush()
        db.add(
            RootFolder(
                name="Scenes",
                content_type="scene",
                path=str(media_root),
                is_default=True,
                create_missing=True,
            )
        )
        db.commit()

        first = import_specific_media_file(
            db,
            scene=scene,
            source=first_source,
            release_title="Duplicate Scene",
            settings=settings,
        )
        db.commit()
        duplicate = import_specific_media_file(
            db,
            scene=scene,
            source=duplicate_source,
            release_title="Duplicate Scene",
            settings=settings,
        )
        db.commit()

        rows = db.scalars(select(MediaFile).where(MediaFile.scene_id == scene.id).order_by(MediaFile.id)).all()
        assert len(rows) == 1
        assert duplicate.id == first.id == rows[0].id
        assert Path(rows[0].path).exists()
        history = db.scalars(select(History).where(History.event_type == "duplicate_removed")).all()
        assert len(history) == 1

        import_specific_media_file(
            db,
            scene=scene,
            source=different_source,
            release_title="Duplicate Scene",
            settings=settings,
        )
        db.commit()
        rows = db.scalars(select(MediaFile).where(MediaFile.scene_id == scene.id).order_by(MediaFile.id)).all()
        assert len(rows) == 2
    engine.dispose()


def test_scanner_runs_exact_duplicate_cleanup():
    source = (ROOT / "scarletx" / "media_library.py").read_text(encoding="utf-8")
    assert "remove_exact_duplicates(db" in source
    assert "duplicates_removed" in source
    assert hasattr(media_library, "remove_exact_duplicates")


def test_general_settings_no_longer_exposes_or_stores_application_name():
    assert "app_name" not in GeneralSettingsWrite.model_fields

    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    routes = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    store = (ROOT / "scarletx" / "settings_store.py").read_text(encoding="utf-8")

    assert "Application name" not in frontend
    assert 'id="appName"' not in frontend
    assert "app_name:val('#appName')" not in frontend
    assert '"general": {"app_name": settings.app_name' not in routes
    assert '"app_name":d.app_name' not in store
    assert '"app_name"' in store and "LEGACY_KEYS" in store
