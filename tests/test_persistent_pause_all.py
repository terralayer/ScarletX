from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx import downloader_state_hotfix
from scarletx.db import Base
from scarletx.downloader_state_hotfix import (
    enqueue_url_hotfix,
    install_downloader_state_hotfixes,
    pause_all_native_downloads,
    process_job_hotfix,
    resume_native_download_hotfix,
)
from scarletx.models import NativeUsenetJob, TrackedDownload
from scarletx.usenet import worker
from scarletx.usenet import scheduler


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'pause-all.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _native_job(job_id: str, status: str) -> NativeUsenetJob:
    return NativeUsenetJob(
        id=job_id,
        title=job_id.title(),
        nzb_url=f"https://example.invalid/{job_id}.nzb",
        status=status,
    )


def test_no_job_pause_persists_across_fresh_sessions(session_factory):
    with session_factory() as fresh_db:
        assert downloader_state_hotfix.native_download_control(fresh_db) == {
            "paused": False
        }

    with session_factory() as db:
        assert pause_all_native_downloads(db) == {
            "paused": 0,
            "global_paused": True,
        }

    with session_factory() as fresh_db:
        assert downloader_state_hotfix.native_download_control(fresh_db) == {
            "paused": True
        }

    with session_factory() as db:
        assert downloader_state_hotfix.resume_all_native_downloads(db) == {
            "resumed": 0,
            "global_paused": False,
        }

    with session_factory() as fresh_db:
        assert downloader_state_hotfix.native_download_control(fresh_db) == {
            "paused": False
        }


def test_bulk_resume_releases_only_paused_jobs(session_factory):
    statuses = (
        "queued",
        "downloading",
        "paused",
        "postprocessing",
        "failed",
        "completed",
        "cancelled",
    )
    with session_factory() as db:
        for status in statuses:
            db.add(_native_job(status, status))
            db.add(
                TrackedDownload(
                    nzo_id=status,
                    release_title=status.title(),
                    status=status,
                    client_status=status,
                )
            )
        db.commit()

        assert pause_all_native_downloads(db) == {
            "paused": 2,
            "global_paused": True,
        }
        assert downloader_state_hotfix.resume_all_native_downloads(db) == {
            "resumed": 3,
            "global_paused": False,
        }

    with session_factory() as db:
        jobs = {
            row.id: row.status for row in db.scalars(select(NativeUsenetJob)).all()
        }
        tracked = {
            row.nzo_id: (row.status, row.client_status)
            for row in db.scalars(select(TrackedDownload)).all()
        }

    assert jobs == {
        "queued": "queued",
        "downloading": "queued",
        "paused": "queued",
        "postprocessing": "postprocessing",
        "failed": "failed",
        "completed": "completed",
        "cancelled": "cancelled",
    }
    assert tracked == {
        "queued": ("queued", "queued"),
        "downloading": ("queued", "queued"),
        "paused": ("queued", "queued"),
        "postprocessing": ("postprocessing", "postprocessing"),
        "failed": ("failed", "failed"),
        "completed": ("completed", "completed"),
        "cancelled": ("cancelled", "cancelled"),
    }


def test_new_enqueue_is_held_while_global_pause_is_persistent(
    session_factory, monkeypatch
):
    monkeypatch.setattr(worker, "native_client_ready", lambda _settings: True)
    with session_factory() as db:
        pause_all_native_downloads(db)

    job_id = enqueue_url_hotfix(
        session_factory,
        object(),
        "https://example.invalid/new.nzb",
        "New",
    )

    with session_factory() as db:
        assert db.get(NativeUsenetJob, job_id).status == "paused"


def test_concurrent_enqueues_and_pause_leave_every_transfer_held(
    session_factory, monkeypatch
):
    monkeypatch.setattr(worker, "native_client_ready", lambda _settings: True)
    barrier = Barrier(7)

    def enqueue(index: int) -> None:
        barrier.wait()
        enqueue_url_hotfix(
            session_factory,
            object(),
            f"https://example.invalid/{index}.nzb",
            f"Job {index}",
        )

    def pause() -> None:
        barrier.wait()
        with session_factory() as db:
            pause_all_native_downloads(db)

    with ThreadPoolExecutor(max_workers=7) as executor:
        futures = [executor.submit(enqueue, index) for index in range(6)]
        futures.append(executor.submit(pause))
        for future in futures:
            future.result(timeout=10)

    with session_factory() as db:
        assert downloader_state_hotfix.native_download_control(db) == {
            "paused": True
        }
        assert {
            row.status for row in db.scalars(select(NativeUsenetJob)).all()
        } == {"paused"}


def test_concurrent_worker_claim_and_pause_leave_transfer_held(session_factory):
    with session_factory() as db:
        db.add(_native_job("claim-race", "queued"))
        db.commit()

    barrier = Barrier(2)

    def claim() -> bool:
        barrier.wait()
        return worker._enter_transfer_state(session_factory, "claim-race")

    def pause() -> None:
        barrier.wait()
        with session_factory() as db:
            pause_all_native_downloads(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claim_result = executor.submit(claim)
        pause_result = executor.submit(pause)
        claim_result.result(timeout=10)
        pause_result.result(timeout=10)

    with session_factory() as db:
        assert downloader_state_hotfix.native_download_control(db) == {
            "paused": True
        }
        assert db.get(NativeUsenetJob, "claim-race").status == "paused"


def test_worker_boundary_persists_hold_for_job_that_raced_in(
    session_factory, monkeypatch
):
    with session_factory() as db:
        pause_all_native_downloads(db)
        db.add(_native_job("raced", "queued"))
        db.commit()

    called = False

    async def should_not_process(_session_factory, _settings, _job_id):
        nonlocal called
        called = True

    monkeypatch.setattr(downloader_state_hotfix, "_ORIGINAL_PROCESS_JOB", should_not_process)
    asyncio.run(process_job_hotfix(session_factory, object(), "raced"))

    with session_factory() as db:
        assert db.get(NativeUsenetJob, "raced").status == "paused"
    assert called is False


def test_worker_never_reclaims_a_persisted_paused_job(session_factory):
    with session_factory() as db:
        db.add(_native_job("already-held", "paused"))
        db.commit()

    asyncio.run(worker.process_job(session_factory, object(), "already-held"))

    with session_factory() as db:
        assert db.get(NativeUsenetJob, "already-held").status == "paused"


def test_inflight_worker_resumes_from_hold_as_downloading(session_factory):
    class Settings:
        native_usenet_speed_limit_mb_s = 0

    with session_factory() as db:
        db.add(_native_job("inflight", "downloading"))
        db.commit()
        pause_all_native_downloads(db)

    async def exercise_resume():
        waiting = asyncio.create_task(
            worker._wait_if_paused(session_factory, "inflight", Settings())
        )
        await asyncio.sleep(0.05)
        with session_factory() as db:
            downloader_state_hotfix.resume_all_native_downloads(db)
        return await asyncio.wait_for(waiting, timeout=2)

    assert asyncio.run(exercise_resume()) == 0
    with session_factory() as db:
        assert db.get(NativeUsenetJob, "inflight").status == "downloading"


def test_restart_holds_interrupted_transfer_but_keeps_postprocessing_runnable(
    session_factory,
):
    with session_factory() as db:
        pause_all_native_downloads(db)
        db.add_all(
            [
                _native_job("interrupted-transfer", "downloading"),
                _native_job("interrupted-processing", "postprocessing"),
            ]
        )
        db.commit()

    scheduler._recover_interrupted_jobs(session_factory)

    with session_factory() as db:
        assert db.get(NativeUsenetJob, "interrupted-transfer").status == "paused"
        assert db.get(NativeUsenetJob, "interrupted-processing").status == (
            "postprocessing"
        )
    assert scheduler._queued_job_ids(session_factory, limit=2) == [
        "interrupted-processing"
    ]


def test_postprocessing_only_pauses_when_it_needs_another_transfer(
    session_factory,
):
    with session_factory() as db:
        pause_all_native_downloads(db)
        db.add(_native_job("recovery-transfer", "postprocessing"))
        db.commit()

    entered = worker._enter_transfer_state(
        session_factory,
        "recovery-transfer",
        allowed_statuses={"postprocessing", "downloading"},
        pause_on_block=True,
    )

    assert entered is False
    with session_factory() as db:
        assert db.get(NativeUsenetJob, "recovery-transfer").status == "paused"

    with session_factory() as db:
        downloader_state_hotfix.resume_all_native_downloads(db)
    assert worker._enter_transfer_state(session_factory, "recovery-transfer") is True


def test_individual_resume_is_blocked_during_global_pause(session_factory):
    with session_factory() as db:
        db.add(_native_job("held", "paused"))
        db.commit()
        pause_all_native_downloads(db)

        with pytest.raises(HTTPException) as exc_info:
            resume_native_download_hotfix("held", db)

    assert exc_info.value.status_code == 409
    assert "Resume All" in str(exc_info.value.detail)


def test_bulk_resume_does_not_resurrect_paused_job_pending_cancellation(
    session_factory,
):
    with session_factory() as db:
        job = _native_job("pending-cancel", "paused")
        job.cancel_requested = True
        db.add(job)
        db.add(
            TrackedDownload(
                nzo_id=job.id,
                release_title=job.title,
                status="cancelled",
                client_status="cancelled",
            )
        )
        db.commit()
        pause_all_native_downloads(db)

        assert downloader_state_hotfix.resume_all_native_downloads(db) == {
            "resumed": 0,
            "global_paused": False,
        }

    with session_factory() as db:
        job = db.get(NativeUsenetJob, "pending-cancel")
        tracked = db.scalar(
            select(TrackedDownload).where(
                TrackedDownload.nzo_id == "pending-cancel"
            )
        )
        assert (job.status, job.cancel_requested) == ("paused", True)
        assert (tracked.status, tracked.client_status) == (
            "cancelled",
            "cancelled",
        )


def test_control_routes_are_registered_with_the_approved_contract():
    app = FastAPI()

    async def placeholder(job_id: str):
        return {"id": job_id}

    app.add_api_route(
        "/api/downloads/native/{job_id}/resume", placeholder, methods=["POST"]
    )
    app.add_api_route(
        "/api/downloads/native/{job_id}/reprocess", placeholder, methods=["POST"]
    )
    install_downloader_state_hotfixes(app)

    routes = {
        (route.path, method)
        for route in app.routes
        for method in (getattr(route, "methods", set()) or set())
    }
    assert ("/api/downloads/native/control", "GET") in routes
    assert ("/api/downloads/native/pause-all", "POST") in routes
    assert ("/api/downloads/native/resume-all", "POST") in routes
