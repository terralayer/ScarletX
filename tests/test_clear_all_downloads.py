from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import NativeUsenetJob, TrackedDownload, TrackedDownloadMeta
from scarletx.routes import application


def test_clear_all_downloads_cancels_jobs_and_removes_only_download_staging(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'clear-all.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    download_root = tmp_path / "downloads"
    incomplete = download_root / "incomplete"
    complete = download_root / "complete"
    failed = download_root / "failed"
    media_root = tmp_path / "media"
    imported = media_root / "already-imported.mp4"
    imported.parent.mkdir(parents=True)
    imported.write_bytes(b"keep")

    rows = [
        ("queued", "queued", incomplete / "queued" / "part.bin"),
        ("downloading", "downloading", incomplete / "downloading" / "part.bin"),
        ("paused", "paused", incomplete / "paused" / "part.bin"),
        ("postprocessing", "postprocessing", incomplete / "postprocessing" / "part.bin"),
        ("completed", "completed", complete / "completed" / "scene.nzb"),
        ("failed", "failed", failed / "failed" / "error.nzb"),
        ("cancelled", "cancelled", incomplete / "cancelled" / "part.bin"),
    ]
    for _job_id, _status, path in rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"download")

    with factory() as db:
        for job_id, status, path in rows:
            db.add(NativeUsenetJob(
                id=job_id,
                title=job_id.title(),
                nzb_url=f"https://example.invalid/{job_id}.nzb",
                status=status,
                output_path=str(path),
            ))
            tracked = TrackedDownload(
                nzo_id=job_id,
                release_title=job_id.title(),
                status=status,
                client_status=status,
                storage_path=str(path),
            )
            db.add(tracked)
            db.flush()
            db.add(TrackedDownloadMeta(tracked_download_id=tracked.id))
        db.commit()

        cancelled = []
        monkeypatch.setattr(application, "request_native_cancel", cancelled.append)
        result = application.clear_all_downloads(
            db=db,
            settings=SimpleNamespace(
                native_usenet_incomplete_dir=str(incomplete),
                native_usenet_complete_dir=str(complete),
            ),
        )

        assert result == {"cleared": len(rows), "cancelled": 4}
        assert cancelled == ["queued", "downloading", "paused", "postprocessing"]
        assert db.scalars(select(NativeUsenetJob)).all() == []
        assert db.scalars(select(TrackedDownload)).all() == []
        assert db.scalars(select(TrackedDownloadMeta)).all() == []

    assert all(not Path(path).exists() for _job_id, _status, path in rows)
    assert imported.exists()
    engine.dispose()
