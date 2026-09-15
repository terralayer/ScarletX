from __future__ import annotations

import threading
from contextlib import contextmanager

from ..background_signals import native_queue_signal


class _SharedProcessingCapacity:
    """Process-wide capacity gate for CPU/disk-heavy Usenet post-processing."""

    def __init__(self, limit: int):
        self._condition = threading.Condition(threading.RLock())
        self._limit = max(1, int(limit))
        self._active = 0

    @property
    def limit(self) -> int:
        with self._condition:
            return self._limit

    @property
    def active(self) -> int:
        with self._condition:
            return self._active

    def set_limit(self, limit: int) -> int:
        with self._condition:
            self._limit = max(1, int(limit))
            self._condition.notify_all()
            return self._limit

    def acquire(self) -> None:
        with self._condition:
            while self._active >= self._limit:
                self._condition.wait()
            self._active += 1

    def release(self) -> None:
        with self._condition:
            if self._active <= 0:
                raise RuntimeError("Processing capacity released without a lease")
            self._active -= 1
            self._condition.notify()

    @contextmanager
    def slot(self):
        self.acquire()
        try:
            yield
        finally:
            self.release()


_GLOBAL_PROCESSING_CAPACITY = _SharedProcessingCapacity(1)
_INSTALL_LOCK = threading.RLock()


def configure_processing_limit(limit: int) -> int:
    return _GLOBAL_PROCESSING_CAPACITY.set_limit(max(1, min(int(limit), 3)))


def install_processing_capacity(worker_module) -> None:
    """Bound repair/extract work independently from network scene slots.

    The downloader-state hotfix replaces ``worker.process_job`` during app
    composition, so this installer patches only stable lower boundaries:
    synchronous post-processing and durable status transitions. The scheduler
    configures the live processing limit from runtime settings.
    """

    with _INSTALL_LOCK:
        if getattr(worker_module, "_scarletx_processing_capacity_installed", False):
            return

        original_postprocess = worker_module.postprocess_payload
        original_set_job = worker_module._set_job

        def postprocess_payload(*args, **kwargs):
            with _GLOBAL_PROCESSING_CAPACITY.slot():
                return original_postprocess(*args, **kwargs)

        def set_job(session_factory, job_id, **values):
            result = original_set_job(session_factory, job_id, **values)
            if values.get("status") in {
                "downloading",
                "postprocessing",
                "completed",
                "failed",
                "cancelled",
            }:
                native_queue_signal.notify()
            return result

        worker_module.postprocess_payload = postprocess_payload
        worker_module._set_job = set_job
        worker_module._SharedProcessingCapacity = _SharedProcessingCapacity
        worker_module._GLOBAL_PROCESSING_CAPACITY = _GLOBAL_PROCESSING_CAPACITY
        worker_module.configure_processing_limit = configure_processing_limit
        worker_module._scarletx_processing_capacity_installed = True
