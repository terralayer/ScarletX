from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _completed(payload: dict) -> SimpleNamespace:
    return SimpleNamespace(stdout=json.dumps(payload))


def test_probe_rejects_zero_byte_media_before_ffprobe(tmp_path, monkeypatch):
    from scarletx import media_library

    path = tmp_path / "zero.mkv"
    path.write_bytes(b"")

    def should_not_run(*_args, **_kwargs):
        raise AssertionError("ffprobe should not run for a zero-byte file")

    monkeypatch.setattr(media_library, "_run", should_not_run)

    with pytest.raises(media_library.MediaLibraryError, match="empty|zero-byte"):
        media_library.probe_path(path)


def test_probe_rejects_payload_without_video_stream(tmp_path, monkeypatch):
    from scarletx import media_library

    path = tmp_path / "audio-only.mkv"
    path.write_bytes(b"not-empty")
    monkeypatch.setattr(
        media_library,
        "_run",
        lambda *_args, **_kwargs: _completed(
            {
                "streams": [{"codec_type": "audio", "codec_name": "aac"}],
                "format": {"duration": "120.0", "format_name": "matroska"},
            }
        ),
    )

    with pytest.raises(media_library.MediaLibraryError, match="video stream"):
        media_library.probe_path(path)


@pytest.mark.parametrize("duration", ["0", "-1", None])
def test_probe_rejects_nonpositive_or_missing_duration(tmp_path, monkeypatch, duration):
    from scarletx import media_library

    path = tmp_path / "bad-duration.mkv"
    path.write_bytes(b"not-empty")
    monkeypatch.setattr(
        media_library,
        "_run",
        lambda *_args, **_kwargs: _completed(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                    }
                ],
                "format": {
                    "duration": duration,
                    "format_name": "matroska",
                    "bit_rate": "8000000",
                },
            }
        ),
    )

    with pytest.raises(media_library.MediaLibraryError, match="duration"):
        media_library.probe_path(path)


def test_valid_probe_allows_missing_audio_but_persists_video_details(tmp_path, monkeypatch):
    from scarletx import media_library

    path = tmp_path / "valid.mkv"
    path.write_bytes(b"not-empty")
    monkeypatch.setattr(
        media_library,
        "_run",
        lambda *_args, **_kwargs: _completed(
            {
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "hevc",
                        "width": 3840,
                        "height": 2160,
                    }
                ],
                "format": {
                    "duration": "60.5",
                    "format_name": "matroska,webm",
                    "bit_rate": "12000000",
                },
            }
        ),
    )

    details = media_library.probe_path(path)

    assert details == {
        "duration_seconds": 60.5,
        "width": 3840,
        "height": 2160,
        "video_codec": "hevc",
        "audio_codec": None,
        "container": "matroska,webm",
        "bitrate_bps": 12000000,
    }


def test_unchanged_media_reuses_persisted_probe_without_ffprobe(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from scarletx import media_library
    from scarletx.db import Base
    from scarletx.models import MediaFile, MediaProbe, Scene

    engine = create_engine(f"sqlite:///{tmp_path / 'probe-cache.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    path = tmp_path / "cached.mkv"
    path.write_bytes(b"cached-media")
    stat = path.stat()

    with factory() as db:
        scene = Scene(tpdb_id="probe-cache-scene", title="Probe Cache", content_type="scene")
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path=str(path), size_bytes=stat.st_size)
        db.add(media)
        db.flush()
        db.add(
            MediaProbe(
                media_file_id=media.id,
                duration_seconds=42.0,
                width=1920,
                height=1080,
                video_codec="h264",
                file_mtime=stat.st_mtime,
                size_bytes=stat.st_size,
            )
        )
        db.commit()
        media_id = media.id

    def should_not_probe(_path: Path):
        raise AssertionError("unchanged media should reuse the persisted probe")

    monkeypatch.setattr(media_library, "probe_path", should_not_probe)
    monkeypatch.setattr(media_library, "tool_status", lambda: {"ffmpeg": False, "ffprobe": True})

    with factory() as db:
        media = db.get(MediaFile, media_id)
        probe = media_library.index_media_file(db, media, generate_art=False)
        assert probe.duration_seconds == 42.0
        assert probe.width == 1920
        assert probe.height == 1080
