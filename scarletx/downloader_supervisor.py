from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from sqlalchemy import select, update

from .models import NativeUsenetJob, utcnow
from .usenet.worker import native_worker_loop

Worker = Callable[[object, Callable], Awaitable[None]]


class DownloaderSupervisor:
    """Own and recover the single in-process native downloader task."""

    def __init__(
        self,
        session_factory,
        settings_loader: Callable,
        *,
        worker: Worker = native_worker_loop,
        restart_delay: float = 2.0,
    ) -> None:
        self._session_factory = session_factory
        self._settings_loader = settings_loader
        self._worker = worker
        self._restart_delay = max(0.0, float(restart_delay))
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._stopping = False
        self._state = "failed"
        self._last_error: str | None = None
        self._last_restart_at: datetime | None = None

    async def start(self) -> dict:
        async with self._lock:
            if self._task is None or self._task.done():
                self._stopping = False
                self._launch()
            return self.status()

    def _launch(self) -> None:
        self._state = "running"
        self._task = asyncio.create_task(self._run_worker(), name="scarletx-native-downloader")

    async def _run_worker(self) -> None:
        current = asyncio.current_task()
        try:
            await self._worker(self._session_factory, self._settings_loader)
            error = "Downloader worker exited unexpectedly"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = str(exc)[:2000] or exc.__class__.__name__

        self._last_error = error
        self._state = "failed"
        if self._restart_delay:
            await asyncio.sleep(self._restart_delay)
        if not self._stopping and self._task is current:
            self._last_restart_at = utcnow()
            self._launch()

    def _active_job_ids(self) -> list[str]:
        with self._session_factory() as db:
            return list(db.scalars(
                select(NativeUsenetJob.id).where(
                    NativeUsenetJob.status.in_(("downloading", "postprocessing"))
                )
            ).all())

    def _requeue(self, job_ids: list[str]) -> int:
        if not job_ids:
            return 0
        with self._session_factory() as db:
            result = db.execute(
                update(NativeUsenetJob)
                .where(NativeUsenetJob.id.in_(job_ids))
                .values(status="queued", speed_bps=0.0, eta_seconds=None, error=None)
            )
            db.commit()
            return int(result.rowcount or 0)

    async def restart(self) -> dict:
        async with self._lock:
            self._state = "restarting"
            interrupted = self._active_job_ids()
            previous = self._task
            self._task = None
            if previous is not None and not previous.done():
                previous.cancel()
                try:
                    await previous
                except asyncio.CancelledError:
                    pass
            requeued = self._requeue(interrupted)
            self._stopping = False
            self._last_restart_at = utcnow()
            self._launch()
            return {**self.status(), "requeued": requeued}

    async def stop(self) -> None:
        async with self._lock:
            self._stopping = True
            task = self._task
            self._task = None
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            self._state = "failed"

    def status(self) -> dict:
        task = self._task
        return {
            "state": self._state,
            "alive": bool(task is not None and not task.done()),
            "last_error": self._last_error,
            "last_restart_at": self._last_restart_at,
        }
