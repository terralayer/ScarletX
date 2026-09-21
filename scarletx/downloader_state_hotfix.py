from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import download_clients
from .background_signals import completed_import_signal, native_queue_signal
from .config import Settings
from .db import get_session
from .download_pause import (
    DOWNLOAD_CONTROL_LOCK,
    global_downloads_paused,
    set_global_download_pause,
)
from .models import NativeUsenetJob, TrackedDownload, utcnow
from .routes import application as legacy_application
from .usenet import worker


_ENQUEUE_LOCK = DOWNLOAD_CONTROL_LOCK
_ORIGINAL_ENQUEUE_URL = worker.enqueue_url
_ORIGINAL_PROCESS_JOB = worker.process_job
_ORIGINAL_REPROCESS = legacy_application.reprocess_native_download


def enqueue_url_hotfix(session_factory, settings, url: str, title: str) -> str:
    """Serialize the active-job lookup + enqueue operation inside one ScarletX process."""
    with _ENQUEUE_LOCK:
        return _ORIGINAL_ENQUEUE_URL(session_factory, settings, url, title)


async def process_job_hotfix(session_factory, settings, job_id: str) -> None:
    """Persist the hold if a queue-selection race reaches the worker boundary."""
    with _ENQUEUE_LOCK:
        with session_factory() as db:
            job = db.get(NativeUsenetJob, job_id)
            if job is None:
                return
            if job.cancel_requested:
                raise asyncio.CancelledError
            if job.status == "paused":
                return
            if global_downloads_paused(db) and job.status in {"queued", "downloading"}:
                job.status = "paused"
                job.speed_bps = 0.0
                job.eta_seconds = None
                tracked = db.scalar(
                    select(TrackedDownload)
                    .where(TrackedDownload.nzo_id == job.id)
                    .limit(1)
                )
                if tracked is not None and tracked.status in {"queued", "downloading"}:
                    tracked.status = "paused"
                    tracked.client_status = "paused"
                db.commit()
                return
    await _ORIGINAL_PROCESS_JOB(session_factory, settings, job_id)


def resume_native_download_hotfix(job_id: str, db: Session = Depends(get_session)):
    if global_downloads_paused(db):
        raise HTTPException(
            409,
            "Downloads are paused globally; use Resume All before resuming an individual download",
        )
    job = legacy_application._native_job_or_404(db, job_id)
    if job.status not in {"paused", "failed"}:
        raise HTTPException(409, f"Cannot resume a {job.status} job")

    job.status = "queued"
    job.cancel_requested = False
    job.error = None
    job.completed_at = None
    job.speed_bps = 0.0
    job.eta_seconds = None

    tracked = db.scalar(
        select(TrackedDownload)
        .where(TrackedDownload.nzo_id == job.id)
        .limit(1)
    )
    if tracked is not None:
        tracked.status = "queued"
        tracked.client_status = "queued"
        tracked.error = None
        tracked.completed_at = None
        tracked.imported_at = None
        tracked.last_checked_at = None

    db.commit()
    native_queue_signal.notify()
    return worker.job_dict(job)


def native_download_control(db: Session = Depends(get_session)):
    return {"paused": global_downloads_paused(db)}


def pause_all_native_downloads(db: Session = Depends(get_session)):
    """Pause queued and active transfers while leaving post-processing alone."""
    with _ENQUEUE_LOCK:
        set_global_download_pause(db, True)
        jobs = db.scalars(
            select(NativeUsenetJob).where(
                NativeUsenetJob.status.in_({"queued", "downloading"})
            )
        ).all()
        job_ids = [job.id for job in jobs]
        for job in jobs:
            job.status = "paused"
            job.speed_bps = 0.0
            job.eta_seconds = None
        if job_ids:
            tracked = db.scalars(
                select(TrackedDownload).where(
                    TrackedDownload.nzo_id.in_(job_ids),
                    TrackedDownload.status.in_({"queued", "downloading"}),
                )
            ).all()
            for item in tracked:
                item.status = "paused"
                item.client_status = "paused"
        db.commit()
    native_queue_signal.notify()
    return {"paused": len(jobs), "global_paused": True}


def resume_all_native_downloads(db: Session = Depends(get_session)):
    """Clear the durable hold and release paused transfers only."""
    with _ENQUEUE_LOCK:
        set_global_download_pause(db, False)
        jobs = db.scalars(
            select(NativeUsenetJob).where(
                NativeUsenetJob.status == "paused",
                NativeUsenetJob.cancel_requested.is_(False),
            )
        ).all()
        job_ids = [job.id for job in jobs]
        for job in jobs:
            job.status = "queued"
            job.speed_bps = 0.0
            job.eta_seconds = None
        if job_ids:
            tracked = db.scalars(
                select(TrackedDownload).where(
                    TrackedDownload.nzo_id.in_(job_ids),
                    TrackedDownload.status == "paused",
                )
            ).all()
            for item in tracked:
                item.status = "queued"
                item.client_status = "queued"
        db.commit()
    native_queue_signal.notify()
    return {"resumed": len(jobs), "global_paused": False}


async def reprocess_native_download_hotfix(
    job_id: str,
    db: Session = Depends(get_session),
    settings: Settings = Depends(legacy_application.get_runtime_settings),
):
    job = legacy_application._native_job_or_404(db, job_id)
    if job.status != "completed":
        raise HTTPException(409, f"Cannot reprocess a {job.status} job")

    tracked = db.scalar(
        select(TrackedDownload)
        .where(TrackedDownload.nzo_id == job_id)
        .limit(1)
    )
    if tracked is not None and tracked.status == "import_failed":
        tracked.status = "import_pending"
        tracked.client_status = "completed"
        tracked.error = None
        tracked.last_checked_at = None
        tracked.completed_at = tracked.completed_at or utcnow()
        db.commit()

    result = await _ORIGINAL_REPROCESS(job_id=job_id, db=db, settings=settings)
    completed_import_signal.notify()
    return result


def _replace_route(app, path: str, method: str, endpoint) -> None:
    method = method.upper()
    for route in app.router.routes:
        if getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set()):
            route.endpoint = endpoint
            route.dependant.call = endpoint
            return
    raise RuntimeError(f"ScarletX route not found: {method} {path}")


def install_downloader_state_hotfixes(app) -> None:
    # Keep every import site on the same serialized native enqueue implementation.
    worker.enqueue_url = enqueue_url_hotfix
    download_clients.enqueue_url = enqueue_url_hotfix

    # native_worker_loop resolves process_job from worker globals at runtime.
    worker.process_job = process_job_hotfix

    _replace_route(app, "/api/downloads/native/{job_id}/resume", "POST", resume_native_download_hotfix)
    _replace_route(app, "/api/downloads/native/{job_id}/reprocess", "POST", reprocess_native_download_hotfix)
    if not any(getattr(route, "path", None) == "/api/downloads/native/control" for route in app.router.routes):
        app.add_api_route("/api/downloads/native/control", native_download_control, methods=["GET"], name="native_download_control")
    if not any(getattr(route, "path", None) == "/api/downloads/native/pause-all" for route in app.router.routes):
        app.add_api_route("/api/downloads/native/pause-all", pause_all_native_downloads, methods=["POST"], name="pause_all_native_downloads")
    if not any(getattr(route, "path", None) == "/api/downloads/native/resume-all" for route in app.router.routes):
        app.add_api_route("/api/downloads/native/resume-all", resume_all_native_downloads, methods=["POST"], name="resume_all_native_downloads")
