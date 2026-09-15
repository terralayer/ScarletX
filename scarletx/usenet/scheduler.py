from __future__ import annotations

import asyncio

from sqlalchemy import select, update

from ..background_signals import native_queue_signal
from ..models import NativeUsenetJob
from ..status_console import emit_status
from . import worker


DEFAULT_CONCURRENT_DOWNLOADS = 2
MAX_CONCURRENT_DOWNLOADS = 5


def _concurrency_limit(settings) -> int:
    try:
        requested = int(
            getattr(settings, "native_usenet_concurrent_downloads", DEFAULT_CONCURRENT_DOWNLOADS)
        )
    except (TypeError, ValueError):
        requested = DEFAULT_CONCURRENT_DOWNLOADS
    return max(1, min(requested, MAX_CONCURRENT_DOWNLOADS))


def _queued_job_ids(
    session_factory,
    *,
    limit: int,
    exclude: set[str] | None = None,
) -> list[str]:
    """Return the oldest runnable queue entries without active duplicates."""

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
            emit_status(
                "Native Downloader",
                "WORKER FAILED",
                f"{job_id}: {exc.__class__.__name__}",
                severity="error",
            )


async def native_worker_loop(session_factory, settings_loader, poll_seconds: float = 5.0) -> None:
    """Run a bounded set of independent scene downloads."""

    emit_status(
        "Native Downloader",
        "ACTIVE",
        "concurrent scene scheduler; event driven; 60s recovery fallback",
        severity="active",
    )
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
            limit = _concurrency_limit(settings)

            capacity = max(0, limit - len(active))
            for job_id in _queued_job_ids(
                session_factory,
                limit=capacity,
                exclude=set(active),
            ):
                active[job_id] = asyncio.create_task(
                    worker.process_job(session_factory, settings, job_id),
                    name=f"scarletx-download-{job_id}",
                )

            if len(active) >= limit and active:
                await asyncio.wait(
                    tuple(active.values()),
                    timeout=worker.NATIVE_QUEUE_RECOVERY_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                continue

            await native_queue_signal.wait(worker.NATIVE_QUEUE_RECOVERY_SECONDS)
    finally:
        tasks = tuple(active.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
