from __future__ import annotations

import asyncio
import importlib.util
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.dashboard_data import downloaded_scene_page
from scarletx.db import Base
from scarletx.list_queries import scene_summary_page
from scarletx.models import MediaFile, Performer, Scene, Studio


ROOT = Path(__file__).resolve().parents[1]


def _factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'release-order.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_scene_library_is_release_date_desc_with_undated_last_across_cursor_pages(tmp_path):
    engine, factory = _factory(tmp_path)
    with factory() as db:
        db.add_all(
            [
                Scene(tpdb_id="old", title="Old", content_type="scene", release_date=date(2024, 1, 1)),
                Scene(tpdb_id="new", title="New", content_type="scene", release_date=date(2026, 8, 1)),
                Scene(tpdb_id="middle", title="Middle", content_type="scene", release_date=date(2025, 6, 1)),
                Scene(tpdb_id="undated", title="Undated", content_type="scene", release_date=None),
            ]
        )
        db.commit()

        first = scene_summary_page(db, limit=2)
        second = scene_summary_page(db, limit=2, cursor=first["next_cursor"])

        assert [item["title"] for item in first["items"] + second["items"]] == [
            "New",
            "Middle",
            "Old",
            "Undated",
        ]
    engine.dispose()


def test_dashboard_downloaded_scenes_are_recently_released_not_recently_imported(tmp_path):
    engine, factory = _factory(tmp_path)
    with factory() as db:
        old = Scene(tpdb_id="old-dl", title="Old Download", content_type="scene", release_date=date(2023, 1, 1))
        new = Scene(tpdb_id="new-dl", title="New Download", content_type="scene", release_date=date(2026, 7, 1))
        undated = Scene(tpdb_id="undated-dl", title="Undated Download", content_type="scene", release_date=None)
        db.add_all([old, new, undated])
        db.flush()
        db.add_all(
            [
                MediaFile(scene_id=old.id, path=str(tmp_path / "old.mp4")),
                MediaFile(scene_id=new.id, path=str(tmp_path / "new.mp4")),
                MediaFile(scene_id=undated.id, path=str(tmp_path / "undated.mp4")),
            ]
        )
        db.commit()

        page = downloaded_scene_page(db, limit=10)
        assert [item["title"] for item in page["items"]] == [
            "New Download",
            "Old Download",
            "Undated Download",
        ]
    engine.dispose()


def test_recent_studios_follow_latest_downloaded_release(tmp_path):
    from scarletx import dashboard_data

    assert hasattr(dashboard_data, "recent_studios")
    engine, factory = _factory(tmp_path)
    with factory() as db:
        alpha = Studio(tpdb_id="alpha", name="Alpha", is_library=True)
        beta = Studio(tpdb_id="beta", name="Beta", is_library=True)
        db.add_all([alpha, beta])
        db.flush()
        alpha_old = Scene(tpdb_id="a-old", title="Alpha Old", content_type="scene", release_date=date(2025, 1, 1), studio_id=alpha.id)
        alpha_new = Scene(tpdb_id="a-new", title="Alpha New", content_type="scene", release_date=date(2026, 6, 1), studio_id=alpha.id)
        beta_new = Scene(tpdb_id="b-new", title="Beta New", content_type="scene", release_date=date(2026, 8, 1), studio_id=beta.id)
        metadata_only = Scene(tpdb_id="b-meta", title="Metadata Only", content_type="scene", release_date=date(2026, 9, 1), studio_id=beta.id)
        db.add_all([alpha_old, alpha_new, beta_new, metadata_only])
        db.flush()
        for scene in (alpha_old, alpha_new, beta_new):
            db.add(MediaFile(scene_id=scene.id, path=str(tmp_path / f"{scene.tpdb_id}.mp4")))
        db.commit()

        rows = dashboard_data.recent_studios(db, limit=8)
        assert [row["name"] for row in rows] == ["Beta", "Alpha"]
        assert rows[0]["latest_title"] == "Beta New"
        assert rows[0]["release_count"] == 1
        assert rows[1]["latest_title"] == "Alpha New"
        assert rows[1]["release_count"] == 2
    engine.dispose()


def test_dashboard_removes_activity_panels_and_adds_recent_release_studios():
    source = (ROOT / "frontend" / "dashboard_settings_overrides.js").read_text(encoding="utf-8")

    assert "Activity Queue" not in source
    assert "Recent Activity" not in source
    assert "/api/activity/queue" not in source
    assert "/api/history" not in source
    assert "Recently Released Scenes" in source
    assert "Studios with Recent Releases" in source
    assert "/api/dashboard/studios?limit=8" in source


def test_successful_import_boundary_precaches_complete_scene_asset_bundle():
    source = (ROOT / "scarletx" / "download_processing.py").read_text(encoding="utf-8")
    assert "cache_scene_asset_bundle" in source
    assert "await cache_scene_asset_bundle" in source
    assert source.index("index_media_file_by_id") < source.rindex("await cache_scene_asset_bundle")


def test_asset_bundle_caches_scene_variants_performers_studio_and_route_thumbnails(tmp_path, monkeypatch):
    spec = importlib.util.find_spec("scarletx.asset_cache")
    assert spec is not None, "scarletx.asset_cache must own import-time artwork warming"
    from scarletx import asset_cache

    engine, factory = _factory(tmp_path)
    with factory() as db:
        studio = Studio(
            tpdb_id="studio-1",
            name="Studio",
            logo_url="https://img.example/studio-logo.png",
            poster_url="https://img.example/studio-poster.jpg",
            is_library=True,
        )
        performer = Performer(
            tpdb_id="performer-1",
            name="Performer",
            image_url="https://img.example/performer.jpg",
            is_library=True,
        )
        scene = Scene(
            tpdb_id="scene-1",
            title="Scene",
            content_type="scene",
            image_url="https://img.example/scene-image.jpg",
            back_image_url="https://img.example/scene-back.jpg",
            poster_url="https://img.example/scene-poster.jpg",
            studio=studio,
            performers=[performer],
        )
        db.add(scene)
        db.commit()
        scene_id = scene.id

        image_calls = []
        thumb_calls = []
        aliases = []
        studio_cache = []

        async def fake_image(key, urls):
            image_calls.append((key, tuple(urls)))
            return f"raw:{key}".encode(), "image/png"

        async def fake_thumb(key, urls, size, *, contain=False):
            thumb_calls.append((key, tuple(urls), size, contain))
            return b"thumb", "image/webp"

        def fake_alias(key, content, content_type, source_url=None):
            aliases.append((key, content_type, source_url))

        monkeypatch.setattr(asset_cache, "cached_remote_image", fake_image)
        monkeypatch.setattr(asset_cache, "cached_remote_thumbnail", fake_thumb)
        monkeypatch.setattr(asset_cache, "cache_remote_image_bytes", fake_alias)
        monkeypatch.setattr(asset_cache, "prepare_studio_artwork", lambda payload: b"prepared-studio")
        monkeypatch.setattr(asset_cache, "cache_studio_artwork", lambda identifier, payload: studio_cache.append((identifier, payload)))

        result = asyncio.run(asset_cache.cache_scene_asset_bundle(db, scene_id))

        keys = {call[0] for call in image_calls}
        assert {
            "scene:scene-1:image",
            "scene:scene-1:back",
            "scene:scene-1:poster",
            "performer:performer-1",
            "studio:studio-1:logo",
            "studio:studio-1:poster",
        } <= keys
        assert any(row[0] == "scene:scene-1" for row in aliases)
        assert ("scene:scene-1", ("https://img.example/scene-back.jpg", "https://img.example/scene-image.jpg", "https://img.example/scene-poster.jpg"), (320, 180), False) in thumb_calls
        assert ("performer:performer-1", ("https://img.example/performer.jpg",), (320, 480), True) in thumb_calls
        assert studio_cache == [("studio-1", b"prepared-studio")]
        assert result["scene_images"] == 3
        assert result["performer_images"] == 1
        assert result["studio_images"] == 2
    engine.dispose()
