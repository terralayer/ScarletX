from __future__ import annotations

import queue
import threading
import time
from contextlib import contextmanager


PHASES = (
    "receive",
    "decode_write",
    "verify",
    "repair",
    "extract",
    "probe",
    "import",
)


class DownloadPhaseMetrics:
    """Small in-memory phase timer that never records payloads, errors, or secrets."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, dict[str, float | int]]] = {}

    def _phase(self, job_id: str, phase: str) -> dict[str, float | int]:
        phases = self._jobs.setdefault(str(job_id), {})
        return phases.setdefault(
            phase,
            {
                "count": 0,
                "failures": 0,
                "total_seconds": 0.0,
                "max_seconds": 0.0,
                "active": 0,
                "peak_active": 0,
            },
        )

    @contextmanager
    def start(self, job_id: str | None, phase: str):
        if phase not in PHASES:
            raise ValueError(f"Unknown download phase: {phase}")
        if not job_id:
            yield
            return

        started = time.perf_counter()
        with self._lock:
            state = self._phase(str(job_id), phase)
            state["active"] = int(state["active"]) + 1
            state["peak_active"] = max(int(state["peak_active"]), int(state["active"]))
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            elapsed = max(0.0, time.perf_counter() - started)
            with self._lock:
                state = self._phase(str(job_id), phase)
                state["active"] = max(0, int(state["active"]) - 1)
                state["count"] = int(state["count"]) + 1
                state["failures"] = int(state["failures"]) + int(failed)
                state["total_seconds"] = float(state["total_seconds"]) + elapsed
                state["max_seconds"] = max(float(state["max_seconds"]), elapsed)

    def snapshot(self, job_id: str) -> dict[str, dict[str, float | int]]:
        with self._lock:
            phases = self._jobs.get(str(job_id), {})
            return {phase: dict(values) for phase, values in phases.items()}

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(str(job_id), None)


class SegmentResultBuffer:
    """Thread-safe bounded handoff queue for completed segment results."""

    def __init__(self, worker_count: int):
        self.maxsize = max(1, int(worker_count) * 2)
        self._queue: queue.Queue = queue.Queue(maxsize=self.maxsize)
        self._lock = threading.Lock()
        self.peak_size = 0

    def _record_peak(self) -> None:
        size = self._queue.qsize()
        with self._lock:
            self.peak_size = max(self.peak_size, size)

    def put(self, item, block: bool = True, timeout: float | None = None) -> None:
        if timeout is None:
            self._queue.put(item, block=block)
        else:
            self._queue.put(item, block=block, timeout=timeout)
        self._record_peak()

    def put_nowait(self, item) -> None:
        self._queue.put_nowait(item)
        self._record_peak()

    def get(self, block: bool = True, timeout: float | None = None):
        if timeout is None:
            return self._queue.get(block=block)
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self):
        return self._queue.get_nowait()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()


download_phase_metrics = DownloadPhaseMetrics()
