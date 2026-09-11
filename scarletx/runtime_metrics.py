from __future__ import annotations

import threading
from contextlib import contextmanager


class RuntimeMetrics:
    """Tiny in-process counters for background efficiency and media concurrency.

    These metrics intentionally avoid SQLAlchemy hooks or periodic sampling so the
    telemetry itself does not become another source of background CPU usage.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, int] = {
            "native_queue_signal_wakes": 0,
            "native_queue_fallback_wakes": 0,
            "completed_import_signal_wakes": 0,
            "completed_import_fallback_wakes": 0,
            "media_tool_active": 0,
            "media_tool_peak": 0,
        }

    def increment(self, key: str, amount: int = 1) -> int:
        with self._lock:
            value = self._values.get(key, 0) + amount
            self._values[key] = value
            return value

    def set(self, key: str, value: int) -> None:
        with self._lock:
            self._values[key] = value

    @contextmanager
    def media_tool(self):
        with self._lock:
            active = self._values.get("media_tool_active", 0) + 1
            self._values["media_tool_active"] = active
            self._values["media_tool_peak"] = max(self._values.get("media_tool_peak", 0), active)
        try:
            yield
        finally:
            with self._lock:
                self._values["media_tool_active"] = max(0, self._values.get("media_tool_active", 0) - 1)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._values)


runtime_metrics = RuntimeMetrics()
