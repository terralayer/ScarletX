from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.models import TrackedDownload, utcnow


def test_import_retry_backoff_delays_second_attempt():
    from scarletx.download_processing import _import_retry_ready

    tracked = TrackedDownload(
        nzo_id="job-1",
        release_title="Scene",
        status="import_pending",
        error="[import-attempt 1/3] FileImportError: no primary video",
        last_checked_at=utcnow(),
    )

    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=10)) is False
    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=31)) is True


def test_import_retry_backoff_delays_third_attempt_longer():
    from scarletx.download_processing import _import_retry_ready

    tracked = TrackedDownload(
        nzo_id="job-2",
        release_title="Scene",
        status="import_pending",
        error="[import-attempt 2/3] FileImportError: still broken",
        last_checked_at=utcnow(),
    )

    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=60)) is False
    assert _import_retry_ready(tracked, now=tracked.last_checked_at + timedelta(seconds=121)) is True


def test_import_failure_attempt_parser_and_terminal_state():
    from scarletx.download_processing import IMPORT_MAX_ATTEMPTS, _import_failure_attempt

    assert IMPORT_MAX_ATTEMPTS == 3
    assert _import_failure_attempt(None) == 0
    assert _import_failure_attempt("plain old error") == 0
    assert _import_failure_attempt("[import-attempt 2/3] OSError: disk offline") == 2
    assert _import_failure_attempt("[import-attempt 3/3] FileImportError: bad payload") == 3


@pytest.mark.asyncio
async def test_third_import_failure_becomes_terminal_and_keeps_error_detail(tmp_path, monkeypatch):
    from scarletx.config import Settings
    from scarletx.db import Base
    from scarletx.download_processing import process_completed_downloads
    from scarletx.models import NativeUsenetJob, Scene
    import scarletx.download_processing as processing

    engine = create_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)

    completed = tmp_path / "completed"
    completed.mkdir()
    with session() as db:
        scene = Scene(tpdb_id="scene-1", title="Scene One")
        db.add(scene)
        db.flush()
        db.add(
            NativeUsenetJob(
                id="job-1",
                title="Scene One",
                nzb_url="https://example.invalid/one.nzb",
                status="completed",
                output_path=str(completed),
            )
        )
        db.add(
            TrackedDownload(
                nzo_id="job-1",
                release_title="Scene One 1080p",
                scene_tpdb_id="scene-1",
                scene_title="Scene One",
                scene_id=scene.id,
                status="import_pending",
                error="[import-attempt 2/3] OSError: previous failure",
                last_checked_at=utcnow() - timedelta(minutes=3),
            )
        )
        db.commit()

    monkeypatch.setattr(
        processing,
        "import_media_file",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("media disk offline")),
    )

    result = await process_completed_downloads(session, Settings())

    assert result["failed"] == 1
    with session() as db:
        tracked = db.query(TrackedDownload).one()
        assert tracked.status == "import_failed"
        assert tracked.error.startswith("[import-attempt 3/3] OSError: media disk offline")
