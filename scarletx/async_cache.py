from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any


class AsyncLRUCache:
    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[object, tuple[Any, float]] = OrderedDict()
        self._inflight: dict[object, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: object, now: float) -> Any | None:
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if now >= expires_at:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return value

    async def put(self, key: object, value: Any, expires_at: float) -> None:
        async with self._lock:
            self._entries[key] = (value, float(expires_at))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    async def get_or_create(
        self,
        key: object,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(self._run_factory(key, factory))
                self._inflight[key] = task
        return await asyncio.shield(task)

    async def _run_factory(
        self,
        key: object,
        factory: Callable[[], Awaitable[Any]],
    ) -> Any:
        try:
            return await factory()
        finally:
            current = asyncio.current_task()
            async with self._lock:
                if self._inflight.get(key) is current:
                    self._inflight.pop(key, None)
