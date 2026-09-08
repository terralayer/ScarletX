from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.config import Settings
from scarletx.dashboard_data import downloaded_scene_page
from scarletx.db import Base
from scarletx.models import History, MediaFile, MediaProbe, RootFolder, Scene
from scarletx.routes.runtime_overrides import GeneralSettingsRuntimeWrite


ROOT = Path(__file__).resolve().parents[1]


def _session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'dashboard-dedup.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_downloaded_scene_page_filters_metadata_only_and_missing_scenes(tmp_path):
    engine, factory = _session_factory(tmp_path)
    with factory() as db:
        downloaded = Scene(tpdb_id="downloaded", title="Downloaded", content_type="scene")
        wanted = Scene(tpdb_id="wanted", title="Wanted", content_type="scene", monitored=True)
        missing = Scene(tpdb_id="missing", title="Missing", content_type="scene")
        db.add_all([downloaded, wanted, missing])
        db.flush()
        good_media = MediaFile(scene_id=downloaded.id, path=str(tmp_path / "downloaded.mp4"), size_bytes=5)
        missing_media = MediaFile(scene_id=missing.id, path=str(tmp_path / "missing.mp4"), size_bytes=5)
        db.add_all([good_media, missing_media])
        db.flush()
        db.add(MediaProbe(media_file_id=missing_media.id, missing=True))
        db.commit()

        page = downloaded_scene_page(db, limit=10)

        assert page["total"] == 1
        assert [item["id"] for item in page["items"]] == [downloaded.id]
        assert page["items"][0]["has_file"] is True
        assert page["items"][0]["media_id"] == good_media.id
    engine.dispose()


def test_dashboard_uses_downloaded_scene_total_and_recent_page():
    source = (ROOT / "frontend" / "dashboard_settings_overrides.js").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")

    assert "/api/library/scenes/page?limit=8&downloaded_only=true" in source
    assert "recent.total" in source
    assert "detail.textContent='Downloaded'" in source
    assert "No downloaded scenes yet." in source
    assert '<script src="/dashboard_settings_overrides.js"></script>' in index
    assert "COPY frontend/dashboard_settings_overrides.js /usr/share/nginx/html/dashboard_settings_overrides.js" in dockerfile


def test_downloaded_only_scene_route_replaces_legacy_route_once():
    from scarletx.app import app

    routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/library/scenes/page"
        and "GET" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1
    assert "downloaded_only" in routes[0].endpoint.__annotations__ or "downloaded_only" in routes[0].endpoint.__code__.co_varnames


def test_exact_duplicate_import_is_removed_but_same_size_different_content_is_kept(tmp_path):
    # Importing the composed app installs the exact-dedup wrapper at the real import boundary.
    import scarletx.app  # noqa: F401
    from scarletx import library_management

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

        first = library_management.import_specific_media_file(
            db,
            scene=scene,
            source=first_source,
            release_title="Duplicate Scene",
            settings=settings,
        )
        db.commit()
        duplicate = library_management.import_specific_media_file(
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

        library_management.import_specific_media_file(
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


def test_scanner_boundary_runs_exact_duplicate_cleanup():
    import scarletx.app  # noqa: F401
    from scarletx import media_library

    assert getattr(media_library.scan_library, "_scarletx_exact_dedup", False) is True
    source = (ROOT / "scarletx" / "media_dedup.py").read_text(encoding="utf-8")
    assert "remove_exact_duplicates(db)" in source
    assert 'stats["duplicates_removed"]' in source
    assert "full_sha256" in source


def test_general_settings_no_longer_exposes_application_name():
    assert "app_name" not in GeneralSettingsRuntimeWrite.model_fields

    frontend = (ROOT / "frontend" / "dashboard_settings_overrides.js").read_text(encoding="utf-8")
    app_source = (ROOT / "scarletx" / "app.py").read_text(encoding="utf-8")
    assert "Application name" not in frontend
    assert 'id="appName"' not in frontend
    assert "app_name:" not in frontend
    assert "{log_level:val('#logLevel')}" in frontend
    assert 'model_copy(update={"app_name": "ScarletX"})' in app_source

    from scarletx.app import app

    routes = [
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/api/settings/general"
        and "PATCH" in (getattr(route, "methods", set()) or set())
    ]
    assert len(routes) == 1
