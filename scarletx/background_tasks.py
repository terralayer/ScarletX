from __future__ import annotations

import asyncio
import inspect
from collections import deque
from collections.abc import Coroutine
from contextvars import Context
from typing import Any


class BackgroundTaskRegistry:
    """Bound and drain application-owned asyncio tasks."""

    def __init__(self, *, max_tasks: int = 128, failure_limit: int = 32) -> None:
        if max_tasks < 1:
            raise ValueError("max_tasks must be positive")
        if failure_limit < 1:
            raise ValueError("failure_limit must be positive")
        self.max_tasks = max_tasks
        self._tasks: set[asyncio.Task[Any]] = set()
        self._failures: deque[dict[str, str]] = deque(maxlen=failure_limit)

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    @property
    def failures(self) -> list[dict[str, str]]:
        return list(self._failures)

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
        context: Context | None = None,
    ) -> asyncio.Task[Any]:
        if len(self._tasks) >= self.max_tasks:
            if inspect.iscoroutine(coro):
                coro.close()
            raise RuntimeError("background task capacity reached")

        if context is None:
            task = asyncio.create_task(coro, name=name)
        else:
            task = asyncio.create_task(coro, name=name, context=context)
        self._tasks.add(task)
        task.add_done_callback(self._task_finished)
        return task

    def _task_finished(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            error = task.exception()
        except asyncio.CancelledError:
            return
        if error is not None:
            self._failures.append(
                {
                    "name": task.get_name(),
                    "error_type": error.__class__.__name__,
                }
            )

    async def shutdown(self) -> None:
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


class AsyncioTaskProxy:
    """Delegate asyncio while routing create_task through a bounded registry."""

    def __init__(self, asyncio_module: Any, registry: BackgroundTaskRegistry) -> None:
        self._asyncio = asyncio_module
        self._registry = registry

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: str | None = None,
        context: Context | None = None,
    ) -> asyncio.Task[Any]:
        return self._registry.create_task(coro, name=name, context=context)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._asyncio, name)
