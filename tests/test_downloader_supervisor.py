import asyncio

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import NativeUsenetJob


def make_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'supervisor.db'}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_restart_requeues_interrupted_job_and_preserves_paused_job(tmp_path):
    from scarletx.downloader_supervisor import DownloaderSupervisor

    session = make_session(tmp_path)
    with session() as db:
        db.add_all([
            NativeUsenetJob(id="active", title="Active", nzb_url="https://example.invalid/a", status="downloading"),
            NativeUsenetJob(id="paused", title="Paused", nzb_url="https://example.invalid/p", status="paused"),
        ])
        db.commit()

    starts = 0

    async def worker(_session, _settings_loader):
        nonlocal starts
        starts += 1
        await asyncio.Event().wait()

    supervisor = DownloaderSupervisor(session, lambda: object(), worker=worker, restart_delay=0)
    await supervisor.start()
    await asyncio.sleep(0)
    result = await supervisor.restart()
    await asyncio.sleep(0)

    with session() as db:
        states = {row.id: row.status for row in db.scalars(select(NativeUsenetJob)).all()}
    assert states == {"active": "queued", "paused": "paused"}
    assert result["requeued"] == 1
    assert result["state"] == "running"
    assert starts == 2
    await supervisor.stop()


@pytest.mark.asyncio
async def test_unexpected_worker_exit_is_replaced(tmp_path):
    from scarletx.downloader_supervisor import DownloaderSupervisor

    session = make_session(tmp_path)
    starts = 0

    async def crash_once(_session, _settings_loader):
        nonlocal starts
        starts += 1
        if starts == 1:
            raise RuntimeError("worker crashed")
        await asyncio.Event().wait()

    supervisor = DownloaderSupervisor(session, lambda: object(), worker=crash_once, restart_delay=0)
    await supervisor.start()
    for _ in range(5):
        await asyncio.sleep(0)

    status = supervisor.status()
    assert starts == 2
    assert status["state"] == "running"
    assert status["alive"] is True
    assert status["last_error"] == "worker crashed"
    await supervisor.stop()


def test_production_app_exposes_downloader_restart_route():
    from scarletx.main import app

    assert str(app.url_path_for("restart_download_client")) == "/api/download-client/restart"
