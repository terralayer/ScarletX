from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class _Checkpoint:
    timestamp: float
    downloaded_bytes: int


class ProgressCheckpointGate:
    """Bound durable progress writes while keeping live counters unconstrained."""

    def __init__(
        self,
        interval_seconds: float = 2.0,
        byte_threshold: int = 8 * 1024 * 1024,
    ) -> None:
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.byte_threshold = max(1, int(byte_threshold))
        self._checkpoints: dict[str, _Checkpoint] = {}
        self._forced: set[str] = set()
        self._lock = threading.RLock()

    def should_persist(self, job_id: str, downloaded_bytes: int, now: float) -> bool:
        downloaded = max(0, int(downloaded_bytes))
        timestamp = float(now)
        with self._lock:
            previous = self._checkpoints.get(job_id)
            forced = job_id in self._forced
            if (
                previous is None
                or forced
                or timestamp - previous.timestamp >= self.interval_seconds
                or downloaded - previous.downloaded_bytes >= self.byte_threshold
            ):
                self._checkpoints[job_id] = _Checkpoint(timestamp, downloaded)
                self._forced.discard(job_id)
                return True
            return False

    def force(self, job_id: str) -> None:
        with self._lock:
            self._forced.add(job_id)

    def clear(self, job_id: str) -> None:
        with self._lock:
            self._checkpoints.pop(job_id, None)
            self._forced.discard(job_id)
