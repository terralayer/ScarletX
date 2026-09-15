from __future__ import annotations

import threading
from contextlib import contextmanager


class _SharedConnectionBudget:
    """Process-wide lease budget for active NNTP sessions."""

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

    def try_acquire(self) -> bool:
        with self._condition:
            if self._active >= self._limit:
                return False
            self._active += 1
            return True

    def acquire(self) -> None:
        with self._condition:
            while self._active >= self._limit:
                self._condition.wait()
            self._active += 1

    def release(self) -> None:
        with self._condition:
            if self._active <= 0:
                raise RuntimeError("NNTP connection budget released without a lease")
            self._active -= 1
            self._condition.notify()

    @contextmanager
    def slot(self):
        self.acquire()
        try:
            yield
        finally:
            self.release()


_GLOBAL_CONNECTION_BUDGET = _SharedConnectionBudget(200)
_INSTALL_LOCK = threading.RLock()


def configure_global_connection_limit(limit: int) -> int:
    return _GLOBAL_CONNECTION_BUDGET.set_limit(max(1, min(int(limit), 200)))


def install_connection_budget(worker_module) -> None:
    """Cap active leases across all provider pools and scene jobs."""

    with _INSTALL_LOCK:
        if getattr(worker_module, "_scarletx_connection_budget_installed", False):
            return

        pool_class = worker_module._ProviderConnectionPool
        original_try_acquire = pool_class.try_acquire
        original_release = pool_class.release
        original_provider_key = worker_module._provider_pool_key
        original_process_job = worker_module.process_job

        def provider_pool_key(providers, max_retries, global_limit=None):
            key = original_provider_key(providers, max_retries)
            effective_limit = (
                _GLOBAL_CONNECTION_BUDGET.limit
                if global_limit is None
                else max(1, min(int(global_limit), 200))
            )
            return key + (("global_connections", effective_limit),)

        def try_acquire(pool):
            if not _GLOBAL_CONNECTION_BUDGET.try_acquire():
                return None
            try:
                connection = original_try_acquire(pool)
            except BaseException:
                _GLOBAL_CONNECTION_BUDGET.release()
                raise
            if connection is None:
                _GLOBAL_CONNECTION_BUDGET.release()
                return None
            setattr(connection, "_scarletx_global_budget_lease", True)
            return connection

        def release(pool, connection, *, broken=False):
            leased = bool(getattr(connection, "_scarletx_global_budget_lease", False))
            try:
                return original_release(pool, connection, broken=broken)
            finally:
                if leased:
                    try:
                        delattr(connection, "_scarletx_global_budget_lease")
                    except AttributeError:
                        pass
                    _GLOBAL_CONNECTION_BUDGET.release()

        async def process_job(session_factory, settings, job_id):
            configure_global_connection_limit(
                getattr(settings, "native_usenet_max_connections", 200)
            )
            return await original_process_job(session_factory, settings, job_id)

        pool_class.try_acquire = try_acquire
        pool_class.release = release
        worker_module._provider_pool_key = provider_pool_key
        worker_module._SharedConnectionBudget = _SharedConnectionBudget
        worker_module._GLOBAL_CONNECTION_BUDGET = _GLOBAL_CONNECTION_BUDGET
        worker_module.configure_global_connection_limit = configure_global_connection_limit
        worker_module.process_job = process_job
        worker_module._scarletx_connection_budget_installed = True
