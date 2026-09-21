from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from scarletx.media_library import ensure_browser_playback
from scarletx.models import Base, NativeUsenetJob
from scarletx.usenet.worker import completed_rows, failed_rows


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


def test_audio_only_m4a_builds_a_browser_playable_mp4_without_requesting_video(tmp_path, monkeypatch):
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"source")
    commands = []

    def fake_run(args, *, timeout=120):
        commands.append(args)
        Path(args[-1]).write_bytes(b"browser-mp4")

    monkeypatch.setattr("scarletx.media_library._run", fake_run)

    result = ensure_browser_playback(
        23,
        source,
        video_codec="",
        audio_codec="aac",
        generated_root=tmp_path / "generated",
    )

    assert result.name == "playback.mp4"
    assert "0:v:0" not in commands[0]
    assert "-vn" in commands[0]
    assert "0:a:0" in commands[0]


def test_existing_media_library_matching_helpers_are_preserved():
    from scarletx import media_library

    assert callable(media_library._norm)
    assert callable(media_library._match_local_scene)


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


def test_failed_rows_supports_offset_for_real_server_pagination():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    base = datetime(2026, 9, 11, tzinfo=UTC)
    with Session(engine) as db:
        for index in range(45):
            db.add(
                NativeUsenetJob(
                    id=f"failed-{index:02d}",
                    title=f"Failed Scene {index:02d}",
                    nzb_url=f"https://example.invalid/failed-{index}.nzb",
                    status="failed",
                    updated_at=base + timedelta(minutes=index),
                )
            )
        db.commit()

        page = failed_rows(db, limit=20, offset=20)

    assert len(page) == 20
    assert page[0]["id"] == "failed-24"
    assert page[-1]["id"] == "failed-05"


def test_activity_uses_25_active_and_20_completed_and_failed_rows_per_page():
    source = (ROOT / "frontend" / "app.js").read_text()
    activity_lists = (ROOT / "frontend" / "activity_lists.js").read_text()
    queue_owner = (ROOT / "frontend" / "ui_overrides.js").read_text()
    studio_override = (ROOT / "frontend" / "activity_studio_overrides.js").read_text()
    backend = (ROOT / "scarletx" / "routes" / "application.py").read_text()

    assert "ACTIVITY_QUEUE_PAGE_SIZE=25" in source
    assert "ACTIVITY_COMPLETED_PAGE_SIZE=20" in source
    assert "ACTIVITY_FAILED_PAGE_SIZE=20" in source
    assert "activityQueuePage" in source
    assert 'id="activityQueuePageSize"' in source
    assert 'class="download-queue-size"' in source
    assert '<span>Show</span>' in source
    assert '<span>rows</span>' in source
    assert "completed:{page:1,request:0,size:()=>ACTIVITY_COMPLETED_PAGE_SIZE}" in activity_lists
    assert "failed:{page:1,request:0,size:()=>ACTIVITY_FAILED_PAGE_SIZE}" in activity_lists
    assert "`/api/downloads/${kind}?limit=${state.size()}&offset=${(state.page-1)*state.size()}`" in activity_lists
    assert "activityPager(kind,page,total,state.size())" in activity_lists
    assert "request!==state.request||requestedPage!==state.page" in activity_lists
    assert 'data-activity-page="${kind}"' in source
    assert "Object.keys(activitySections)" in activity_lists
    assert ">Previous</button>" in source
    assert ">Next</button>" in source
    assert "$('#queueBadge').textContent=activityQueueTotal||snapshotRows.length" in queue_owner
    assert "const start=(activityQueuePage-1)*ACTIVITY_QUEUE_PAGE_SIZE" in studio_override
    assert "activityQueuePageRows" not in studio_override
    assert "def completed_downloads(limit: int = Query(20" in backend
    assert "def failed_downloads(limit: int = Query(20" in backend
    assert backend.count("offset: int = Query(0, ge=0)") >= 2
    assert backend.count('"total":') >= 2
