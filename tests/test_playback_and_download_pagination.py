from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scarletx.media_library import ensure_browser_playback
from scarletx.models import Base, NativeUsenetJob
from scarletx.usenet.worker import completed_rows


ROOT = Path(__file__).resolve().parents[1]


def test_browser_safe_mp4_uses_original_without_ffmpeg(tmp_path, monkeypatch):
    source = tmp_path / "scene.mp4"
    source.write_bytes(b"original")

    def fail_run(*args, **kwargs):
        raise AssertionError("browser-safe MP4 should not invoke ffmpeg")

    monkeypatch.setattr("scarletx.media_library._run", fail_run)
    result = ensure_browser_playback(
        11,
        source,
        video_codec="h264",
        audio_codec="aac",
        generated_root=tmp_path / "generated",
    )
    assert result == source


def test_incompatible_media_builds_and_reuses_cached_mp4(tmp_path, monkeypatch):
    source = tmp_path / "scene.mkv"
    source.write_bytes(b"source")
    calls = []

    def fake_run(args, *, timeout=120):
        calls.append(args)
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"browser-mp4")
        return None

    monkeypatch.setattr("scarletx.media_library._run", fake_run)
    root = tmp_path / "generated"
    first = ensure_browser_playback(
        22,
        source,
        video_codec="hevc",
        audio_codec="ac3",
        generated_root=root,
    )
    second = ensure_browser_playback(
        22,
        source,
        video_codec="hevc",
        audio_codec="ac3",
        generated_root=root,
    )

    assert first == root / "media" / "22" / "playback.mp4"
    assert second == first
    assert len(calls) == 1
    command = calls[0]
    assert "libx264" in command
    assert "aac" in command
    assert "+faststart" in command


def test_completed_rows_supports_offset_for_real_server_pagination():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    base = datetime(2026, 9, 11, tzinfo=UTC)
    with Session(engine) as db:
        for index in range(45):
            db.add(
                NativeUsenetJob(
                    id=f"job-{index:02d}",
                    title=f"Scene {index:02d}",
                    nzb_url=f"https://example.invalid/{index}.nzb",
                    status="completed",
                    completed_at=base + timedelta(minutes=index),
                )
            )
        db.commit()

        page = completed_rows(db, limit=20, offset=20)

    assert len(page) == 20
    assert page[0]["id"] == "job-24"
    assert page[-1]["id"] == "job-05"


def test_activity_uses_50_active_and_20_completed_rows_per_page():
    source = (ROOT / "frontend" / "app.js").read_text()
    backend = (ROOT / "scarletx" / "routes" / "application.py").read_text()

    assert "ACTIVITY_QUEUE_PAGE_SIZE=50" in source
    assert "ACTIVITY_COMPLETED_PAGE_SIZE=20" in source
    assert "activityQueuePage" in source
    assert "activityCompletedPage" in source
    assert "limit=${ACTIVITY_COMPLETED_PAGE_SIZE}&offset=${completedOffset}" in source
    assert "activityPager" in source
    assert "offset: int = Query(0, ge=0)" in backend
    assert '"total":' in backend
