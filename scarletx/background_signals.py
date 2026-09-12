from __future__ import annotations

import asyncio
import threading


class AsyncWakeSignal:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._event: asyncio.Event | None = None

    async def bind(self) -> None:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._loop is not loop or self._event is None:
                self._loop = loop
                self._event = asyncio.Event()

    def notify(self) -> bool:
        with self._lock:
            loop, event = self._loop, self._event
        if loop is None or event is None or loop.is_closed():
            return False
        loop.call_soon_threadsafe(event.set)
        return True

    async def wait(self, timeout: float) -> bool:
        await self.bind()
        assert self._event is not None
        if self._event.is_set():
            self._event.clear(); return True
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        self._event.clear(); return True


native_queue_signal = AsyncWakeSignal()
completed_import_signal = AsyncWakeSignal()
