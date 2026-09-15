from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


def _same_timezone(value, reference):
    if value is None:
        return None
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    return value


def test_watchdog_columns_upgrade_existing_native_queue(tmp_path):
    from scarletx.migrations import ensure_native_watchdog_columns

    engine = create_engine(f"sqlite:///{tmp_path / 'watchdog-upgrade.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE native_usenet_jobs ("
            "id VARCHAR(64) PRIMARY KEY, status VARCHAR(40) NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
        ensure_native_watchdog_columns(connection)
        ensure_native_watchdog_columns(connection)

    columns = {column["name"] for column in inspect(engine).get_columns("native_usenet_jobs")}
    assert {"watchdog_retries", "retry_after", "quarantined"} <= columns


def test_stale_job_retries_then_quarantines_without_blocking_other_work(tmp_path):
    from scarletx.db import Base
    from scarletx.models import NativeUsenetJob, utcnow
    from scarletx.watchdog import recover_stuck_native_jobs

    engine = create_engine(f"sqlite:///{tmp_path / 'watchdog.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = utcnow()
    with factory() as db:
        db.add_all(
            [
                NativeUsenetJob(
                    id="stuck",
                    title="Stuck",
                    nzb_url="https://example.invalid/stuck.nzb",
                    status="downloading",
                    updated_at=now - timedelta(hours=1),
                ),
                NativeUsenetJob(
                    id="healthy",
                    title="Healthy",
                    nzb_url="https://example.invalid/healthy.nzb",
                    status="downloading",
                    updated_at=now,
                ),
            ]
        )
        db.commit()

    first = recover_stuck_native_jobs(factory, now=now, max_retries=2)
    assert first == {"retried": 1, "quarantined": 0}
    with factory() as db:
        stuck = db.get(NativeUsenetJob, "stuck")
        healthy = db.get(NativeUsenetJob, "healthy")
        assert stuck.status == "queued"
        assert stuck.watchdog_retries == 1
        retry_after = _same_timezone(stuck.retry_after, now)
        assert retry_after is not None and retry_after > now
        assert stuck.quarantined is False
        assert healthy.status == "downloading"

        stuck.status = "downloading"
        stuck.updated_at = now - timedelta(hours=1)
        stuck.retry_after = None
        stuck.watchdog_retries = 2
        db.commit()

    final = recover_stuck_native_jobs(factory, now=now, max_retries=2)
    assert final == {"retried": 0, "quarantined": 1}
    with factory() as db:
        stuck = db.get(NativeUsenetJob, "stuck")
        assert stuck.status == "failed"
        assert stuck.quarantined is True
