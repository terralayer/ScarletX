from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.config import Settings
from scarletx.db import Base
from scarletx.models import MediaFile, Scene


def _media_session(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'streaming.db'}",
        pool_size=1,
        max_overflow=0,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_media_stream_releases_database_connection_before_body_streaming(tmp_path, monkeypatch):
    from scarletx.routes import application

    engine, Session = _media_session(tmp_path)
    media_path = tmp_path / "scene.mp4"
    media_path.write_bytes(b"video")
    with Session() as db:
        scene = Scene(tpdb_id="stream-scene", title="Stream Scene")
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path=str(media_path), size_bytes=5)
        db.add(media)
        db.commit()
        media_id = media.id

    monkeypatch.setattr(application, "SessionLocal", Session)

    response = application.stream_media(media_id)

    assert str(response.path) == str(media_path)
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_request_settings_lookup_does_not_block_the_event_loop(monkeypatch):
    from scarletx.routes import application

    expected = object()

    class SlowSession:
        def __enter__(self):
            time.sleep(0.15)
            return object()

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(application, "SessionLocal", SlowSession)
    monkeypatch.setattr(application, "load_database_settings", lambda _db: expected)

    started = time.perf_counter()
    task = asyncio.create_task(application._load_request_settings())
    await asyncio.sleep(0.02)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.08
    assert task.done() is False
    assert await task is expected


@pytest.mark.asyncio
async def test_scene_card_artwork_uses_local_tpdb_thumbnail(tmp_path, monkeypatch):
    from scarletx.routes import application

    _engine, Session = _media_session(tmp_path)
    with Session() as db:
        db.add(
            Scene(
                tpdb_id="scene-art",
                title="Artwork Scene",
                image_url="https://example.invalid/tpdb-scene.jpg",
            )
        )
        db.commit()

    calls = []

    async def thumbnail(key, urls, size, *, contain=False):
        calls.append((key, urls, size, contain))
        return b"small-webp", "image/webp"

    monkeypatch.setattr(application, "cached_remote_thumbnail", thumbnail)

    with Session() as db:
        response = await application.scene_artwork(
            "scene-art",
            size="card",
            db=db,
            settings=Settings(),
        )

    assert response.body == b"small-webp"
    assert calls == [
        (
            "scene:scene-art",
            ["https://example.invalid/tpdb-scene.jpg"],
            (320, 180),
            False,
        )
    ]
