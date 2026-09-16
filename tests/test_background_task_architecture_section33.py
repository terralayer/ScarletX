from __future__ import annotations

import asyncio

import pytest

from scarletx.background_tasks import AsyncioTaskProxy, BackgroundTaskRegistry


@pytest.mark.asyncio
async def test_registry_bounds_and_drains_application_tasks():
    registry = BackgroundTaskRegistry(max_tasks=2)
    proxy = AsyncioTaskProxy(asyncio, registry)
    started = asyncio.Event()

    async def worker():
        started.set()
        await asyncio.Event().wait()

    first = proxy.create_task(worker(), name="first")
    second = proxy.create_task(worker(), name="second")
    await started.wait()

    rejected = worker()
    with pytest.raises(RuntimeError, match="capacity"):
        proxy.create_task(rejected, name="third")

    assert registry.active_count == 2
    await registry.shutdown()
    assert registry.active_count == 0
    assert first.cancelled()
    assert second.cancelled()


@pytest.mark.asyncio
async def test_registry_records_bounded_failure_metadata_without_error_text():
    registry = BackgroundTaskRegistry(max_tasks=4, failure_limit=2)

    async def fail(kind: str):
        if kind == "value":
            raise ValueError("secret detail should not be retained")
        raise RuntimeError("another secret detail")

    registry.create_task(fail("value"), name="value-worker")
    registry.create_task(fail("runtime"), name="runtime-worker")
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    failures = registry.failures
    assert failures == [
        {"name": "value-worker", "error_type": "ValueError"},
        {"name": "runtime-worker", "error_type": "RuntimeError"},
    ]
    assert "secret" not in repr(failures)


@pytest.mark.asyncio
async def test_proxy_delegates_non_task_asyncio_operations():
    registry = BackgroundTaskRegistry(max_tasks=2)
    proxy = AsyncioTaskProxy(asyncio, registry)

    assert proxy.Event is asyncio.Event
    await proxy.sleep(0)


def test_composed_app_installs_managed_background_task_lifecycle():
    from scarletx.app import _managed_lifespan, app, background_task_registry

    assert app.router.lifespan_context is _managed_lifespan
    assert background_task_registry.max_tasks == 128
