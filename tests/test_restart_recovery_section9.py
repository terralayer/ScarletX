from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_requeue_preserves_partial_bytes_and_output_path(tmp_path):
    from scarletx.db import Base
    from scarletx.downloader_supervisor import DownloaderSupervisor
    from scarletx.models import NativeUsenetJob

    engine = create_engine(f"sqlite:///{tmp_path / 'restart-section9.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    partial = tmp_path / "incomplete" / "job"
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id="resume-me",
                title="Resume me",
                nzb_url="https://example.invalid/resume.nzb",
                status="downloading",
                total_bytes=10_000,
                downloaded_bytes=4_096,
                speed_bps=1234.0,
                eta_seconds=9,
                output_path=str(partial),
            )
        )
        db.commit()

    supervisor = DownloaderSupervisor(factory, lambda: object(), restart_delay=0)
    assert supervisor._requeue(["resume-me"]) == 1

    with factory() as db:
        job = db.get(NativeUsenetJob, "resume-me")
        assert job.status == "queued"
        assert job.downloaded_bytes == 4_096
        assert job.total_bytes == 10_000
        assert job.output_path == str(partial)
        assert job.speed_bps == 0.0
        assert job.eta_seconds is None
