from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_queue_selection_is_fifo_bounded_and_ignores_non_runnable_jobs(tmp_path):
    from scarletx.db import Base
    from scarletx.models import NativeUsenetJob, utcnow
    from scarletx.usenet.worker import _queued_job_ids

    engine = create_engine(f"sqlite:///{tmp_path / 'schedule.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = utcnow()
    with factory() as db:
        rows = [
            ("failed-old", "failed", now - timedelta(minutes=5)),
            ("oldest", "queued", now - timedelta(minutes=4)),
            ("paused", "paused", now - timedelta(minutes=3)),
            ("middle", "queued", now - timedelta(minutes=2)),
            ("newest", "queued", now - timedelta(minutes=1)),
        ]
        for job_id, status, created_at in rows:
            db.add(
                NativeUsenetJob(
                    id=job_id,
                    title=job_id,
                    nzb_url=f"https://example.invalid/{job_id}.nzb",
                    status=status,
                    created_at=created_at,
                )
            )
        db.commit()

    assert _queued_job_ids(factory, limit=2) == ["oldest", "middle"]
    assert _queued_job_ids(factory, limit=2, exclude={"oldest"}) == ["middle", "newest"]
    assert _queued_job_ids(factory, limit=0) == []
