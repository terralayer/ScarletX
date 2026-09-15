from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from ..background_signals import native_queue_signal
from ..models import NativeUsenetJob
from ..resource_guard import check_disk_capacity
from ..status_console import emit_status
from . import worker

DEFAULT_CONCURRENT_DOWNLOADS = 2
MAX_CONCURRENT_DOWNLOADS = 5
DEFAULT_CONCURRENT_PROCESSING = 1


def _concurrency_limit(settings) -> int:
    try:
        requested = int(getattr(settings, "native_usenet_concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS))
    except (TypeError, ValueError):
        requested = DEFAULT_CONCURRENT_DOWNLOADS
    return max(1, min(requested, MAX_CONCURRENT_DOWNLOADS))


def _processing_limit(settings) -> int:
    try:
        requested = int(getattr(settings, "native_usenet_concurrent_processing", DEFAULT_CONCURRENT_PROCESSING))
    except (TypeError, ValueError):
        requested = DEFAULT_CONCURRENT_PROCESSING
    return max(1, min(requested, 3))


def _network_capacity(statuses: dict[str, str], *, download_limit: int) -> int:
    active_network = sum(1 for status in statuses.values() if str(status or "").casefold() != "postprocessing")
    return max(0, max(1, int(download_limit)) - active_network)


def _active_statuses(session_factory, job_ids: set[str]) -> dict[str, str]:
    if not job_ids:
        return {}
    with session_factory() as db:
        rows = db.execute(select(NativeUsenetJob.id, NativeUsenetJob.status).where(NativeUsenetJob.id.in_(job_ids))).all()
    statuses = {str(job_id): str(status or "queued") for job_id, status in rows}
    for job_id in job_ids:
        statuses.setdefault(job_id, "queued")
    return statuses


def _queued_job_ids(session_factory, *, limit: int, exclude: set[str] | None = None) -> list[str]:
    if limit <= 0:
        return []
    excluded = set(exclude or ())
    with session_factory() as db:
        rows = db.scalars(
            select(NativeUsenetJob.id)
            .where(NativeUsenetJob.status == "queued")
            .order_by(NativeUsenetJob.created_at.asc(), NativeUsenetJob.id.asc())
            .limit(limit + len(excluded))
        ).all()
    return [job_id for job_id in rows if job_id not in excluded][:limit]


def _resource_ready_for_job(session_factory, settings, job_id: str) -> bool:
    """Admit a queued job only when its remaining bytes fit above the disk reserve."""

    with session_factory() as db:
        job = db.get(NativeUsenetJob, job_id)
        if job is None or job.status != "queued":
            return False
        total_bytes = max(0, int(job.total_bytes or 0))
        downloaded_bytes = max(0, int(job.downloaded_bytes or 0))

    remaining_bytes = max(0, total_bytes - downloaded_bytes)
    try:
        reserve_gib = max(0.0, float(getattr(settings, "minimum_free_space_gb", 0.0) or 0.0))
    except (TypeError, ValueError):
        reserve_gib = 0.0
    reserve_bytes = int(reserve_gib * 1024**3)
    decision = check_disk_capacity(
        getattr(settings, "native_usenet_incomplete_dir", "."),
        required_bytes=remaining_bytes,
        reserve_bytes=reserve_bytes,
    )
    return bool(decision.allowed)


def _consume_finished(active: dict[str, asyncio.Task]) -> None:
    for job_id, task in list(active.items()):
        if not task.done():
            continue
        active.pop(job_id, None)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            emit_status("Native Downloader", "WORKER FAILED", f"{job_id}: {exc.__class__.__name__}", severity="error")


async def _wait_for_capacity_change(active: dict[str, asyncio.Task]) -> None:
    if not active:
        await native_queue_signal.wait(worker.NATIVE_QUEUE_RECOVERY_SECONDS)
        return

    signal_task = asyncio.create_task(native_queue_signal.wait(worker.NATIVE_QUEUE_RECOVERY_SECONDS))
    try:
        done, _pending = await asyncio.wait(
            [*active.values(), signal_task],
            timeout=worker.NATIVE_QUEUE_RECOVERY_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if signal_task in done:
            signal_task.result()
    finally:
        if not signal_task.done():
            signal_task.cancel()
            await asyncio.gather(signal_task, return_exceptions=True)


async def native_worker_loop(session_factory, settings_loader, poll_seconds: float = 5.0) -> None:
    emit_status("Native Downloader", "ACTIVE", "independent download and processing capacity", severity="active")
    await native_queue_signal.bind()
    with session_factory() as db:
        db.execute(
            update(NativeUsenetJob)
            .where(NativeUsenetJob.status.in_(["downloading", "postprocessing"]))
            .values(status="queued", speed_bps=0.0, eta_seconds=None)
        )
        db.commit()

    active: dict[str, asyncio.Task] = {}
    try:
        while True:
            _consume_finished(active)
            settings = settings_loader()
            download_limit = _concurrency_limit(settings)
            processing_limit = _processing_limit(settings)
            configure_processing = getattr(worker, "configure_processing_limit", None)
            if configure_processing is not None:
                configure_processing(processing_limit)
            statuses = _active_statuses(session_factory, set(active))
            network_capacity = _network_capacity(statuses, download_limit=download_limit)
            total_capacity = max(0, download_limit + processing_limit - len(active))
            capacity = min(network_capacity, total_capacity)

            started = False
            for job_id in _queued_job_ids(session_factory, limit=capacity, exclude=set(active)):
                if not _resource_ready_for_job(session_factory, settings, job_id):
                    continue
                active[job_id] = asyncio.create_task(
                    worker.process_job(session_factory, settings, job_id),
                    name=f"scarletx-download-{job_id}",
                )
                started = True
            if started:
                await asyncio.sleep(0)
                continue
            await _wait_for_capacity_change(active)
    finally:
        tasks = tuple(active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
