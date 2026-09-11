from __future__ import annotations

import asyncio
import threading

from .runtime_metrics import runtime_metrics


class AsyncWakeSignal:
    """Coalescing thread-safe wake signal with timeout fallback support."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event: asyncio.Event | None = None

    async def bind(self) -> "AsyncWakeSignal":
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is not loop or self._event is None:
                self._loop = loop
                self._event = asyncio.Event()
        return self

    def notify(self) -> bool:
        with self._lock:
            loop = self._loop
            event = self._event
        if loop is None or event is None or loop.is_closed():
            return False
        loop.call_soon_threadsafe(event.set)
        return True

    async def wait(self, timeout: float) -> bool:
        await self.bind()
        with self._lock:
            event = self._event
        assert event is not None
        if event.is_set():
            event.clear()
            runtime_metrics.increment(f"{self.name}_signal_wakes")
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            runtime_metrics.increment(f"{self.name}_fallback_wakes")
            return False
        event.clear()
        runtime_metrics.increment(f"{self.name}_signal_wakes")
        return True


native_queue_signal = AsyncWakeSignal("native_queue")
completed_import_signal = AsyncWakeSignal("completed_import")
