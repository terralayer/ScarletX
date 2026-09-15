from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _session(tmp_path):
    from scarletx.db import Base

    engine = create_engine(f"sqlite:///{tmp_path / 'section10.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_native_download_concurrency_defaults_to_two(monkeypatch):
    from scarletx.config import Settings

    monkeypatch.delenv("SCARLETX_USENET_CONCURRENT_DOWNLOADS", raising=False)
    assert Settings().native_usenet_concurrent_downloads == 2


@pytest.mark.asyncio
async def test_native_worker_runs_two_jobs_without_starting_third(tmp_path, monkeypatch):
    from scarletx.models import NativeUsenetJob
    from scarletx.usenet import worker

    factory = _session(tmp_path)
    with factory() as db:
        for index in range(3):
            db.add(
                NativeUsenetJob(
                    id=f"job-{index}",
                    title=f"Job {index}",
                    nzb_url=f"https://example.invalid/{index}.nzb",
                    status="queued",
                )
            )
        db.commit()

    started: list[str] = []
    release = asyncio.Event()
    two_started = asyncio.Event()

    async def blocked_process(_factory, _settings, job_id):
        started.append(job_id)
        if len(started) >= 2:
            two_started.set()
        await release.wait()

    monkeypatch.setattr(worker, "process_job", blocked_process)

    class Settings:
        native_usenet_concurrent_downloads = 2

    task = asyncio.create_task(worker.native_worker_loop(factory, lambda: Settings()))
    try:
        await asyncio.wait_for(two_started.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert started == ["job-0", "job-1"]
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
