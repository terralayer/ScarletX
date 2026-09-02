from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
import pytest

from scarletx import tpdb
from scarletx.tpdb import ThePornDBClient, ThePornDBError


class _CountingTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict | None = None, *, delay: float = 0.01) -> None:
        self.request_count = 0
        self.payload = payload or {"data": {"id": "network"}}
        self.delay = delay

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return httpx.Response(200, json=self.payload, request=request)


class _ToggleFailureTransport(httpx.AsyncBaseTransport):
    def __init__(self, payload: dict | None = None) -> None:
        self.request_count = 0
        self.fail = True
        self.payload = payload or {"data": {"id": "recovered"}}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        await asyncio.sleep(0.01)
        if self.fail:
            return httpx.Response(503, json={"error": "unavailable"}, request=request)
        return httpx.Response(200, json=self.payload, request=request)


def _async_lru_cache_class():
    from scarletx.async_cache import AsyncLRUCache

    return AsyncLRUCache


@pytest.mark.asyncio
async def test_memory_cache_evicts_least_recently_used_entry_at_512_entries():
    AsyncLRUCache = _async_lru_cache_class()
    cache = AsyncLRUCache(max_entries=512)

    for index in range(512):
        await cache.put(f"key-{index}", {"value": index}, expires_at=1000.0)

    assert await cache.get("key-0", now=1.0) == {"value": 0}
    await cache.put("key-512", {"value": 512}, expires_at=1000.0)

    assert await cache.get("key-0", now=1.0) == {"value": 0}
    assert await cache.get("key-1", now=1.0) is None
    assert await cache.get("key-512", now=1.0) == {"value": 512}


@pytest.mark.asyncio
async def test_memory_cache_expires_entries_at_ttl_boundary():
    AsyncLRUCache = _async_lru_cache_class()
    cache = AsyncLRUCache(max_entries=512)

    await cache.put("scene", {"id": "scene"}, expires_at=10.0)

    assert await cache.get("scene", now=9.999) == {"id": "scene"}
    assert await cache.get("scene", now=10.0) is None


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_fetch():
    AsyncLRUCache = _async_lru_cache_class()
    cache = AsyncLRUCache(max_entries=512)
    started = asyncio.Event()
    release = asyncio.Event()
    factory_calls = 0

    async def slow_factory():
        nonlocal factory_calls
        factory_calls += 1
        started.set()
        await release.wait()
        return {"ok": True}

    first = asyncio.create_task(cache.get_or_create("shared", slow_factory))
    await started.wait()
    second = asyncio.create_task(cache.get_or_create("shared", slow_factory))
    await asyncio.sleep(0)

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first

    release.set()
    assert await second == {"ok": True}
    assert factory_calls == 1


@pytest.mark.asyncio
async def test_failed_shared_fetch_is_removed_and_can_be_retried():
    AsyncLRUCache = _async_lru_cache_class()
    cache = AsyncLRUCache(max_entries=512)
    factory_calls = 0

    async def factory():
        nonlocal factory_calls
        factory_calls += 1
        await asyncio.sleep(0.01)
        if factory_calls == 1:
            raise RuntimeError("first attempt failed")
        return {"ok": True}

    results = await asyncio.gather(
        cache.get_or_create("shared", factory),
        cache.get_or_create("shared", factory),
        return_exceptions=True,
    )

    assert factory_calls == 1
    assert all(isinstance(result, RuntimeError) for result in results)
    assert await cache.get_or_create("shared", factory) == {"ok": True}
    assert factory_calls == 2


@pytest.mark.asyncio
async def test_equivalent_tpdb_requests_share_one_network_call(tmp_path, monkeypatch):
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    transport = _CountingTransport({"data": {"id": "same"}})
    client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=transport,
        max_retries=1,
    )
    try:
        results = await asyncio.gather(
            *(client._get("/scenes/coalesced") for _ in range(20))
        )
    finally:
        await client.aclose()

    assert transport.request_count == 1
    assert all(result == results[0] for result in results)


@pytest.mark.asyncio
async def test_equivalent_parameter_order_uses_one_normalized_request_key(tmp_path, monkeypatch):
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    transport = _CountingTransport({"data": {"id": "same-params"}})
    client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=transport,
        max_retries=1,
    )
    try:
        params_a = {"page": 1, "per_page": 24}
        params_b = {"per_page": 24, "page": 1}
        results = await asyncio.gather(
            *(client._get("/scenes/params", params_a if index % 2 else params_b) for index in range(20))
        )
    finally:
        await client.aclose()

    assert transport.request_count == 1
    assert all(result == results[0] for result in results)


@pytest.mark.asyncio
async def test_distinct_parameter_values_do_not_share_network_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    transport = _CountingTransport({"data": {"id": "distinct"}})
    client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=transport,
        max_retries=1,
    )
    try:
        await asyncio.gather(
            client._get("/scenes/distinct", {"page": 1, "per_page": 24}),
            client._get("/scenes/distinct", {"page": 2, "per_page": 24}),
        )
    finally:
        await client.aclose()

    assert transport.request_count == 2


@pytest.mark.asyncio
async def test_memory_cache_is_shared_across_short_lived_tpdb_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    path = "/scenes/process-memory"
    first_payload = {"data": {"id": "from-first-client"}}
    first_transport = _CountingTransport(first_payload, delay=0)
    first_client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=first_transport,
        max_retries=1,
    )
    try:
        assert await first_client._get(path) == first_payload
    finally:
        await first_client.aclose()

    tpdb._cache_key(path, None).unlink(missing_ok=True)

    second_transport = _CountingTransport({"data": {"id": "network-should-not-run"}}, delay=0)
    second_client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=second_transport,
        max_retries=1,
    )
    try:
        assert await second_client._get(path) == first_payload
    finally:
        await second_client.aclose()

    assert first_transport.request_count == 1
    assert second_transport.request_count == 0


@pytest.mark.asyncio
async def test_coalesced_tpdb_failure_is_not_cached_as_success(tmp_path, monkeypatch):
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    transport = _ToggleFailureTransport()
    client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=transport,
        max_retries=1,
    )
    try:
        failures = await asyncio.gather(
            *(client._get("/scenes/retry-after-failure") for _ in range(20)),
            return_exceptions=True,
        )
        assert transport.request_count == 1
        assert all(isinstance(result, ThePornDBError) for result in failures)

        transport.fail = False
        assert await client._get("/scenes/retry-after-failure") == {"data": {"id": "recovered"}}
        assert transport.request_count == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_stale_disk_cache_remains_outage_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    path = "/scenes/stale-fallback"
    stale_payload = {"data": {"id": "stale"}}
    cache_path = tpdb._cache_key(path, None)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(stale_payload))
    stale_time = time.time() - 90000
    os.utime(cache_path, (stale_time, stale_time))

    transport = _ToggleFailureTransport()
    client = ThePornDBClient(
        api_key="",
        base_url="https://cache-test.invalid",
        transport=transport,
        max_retries=1,
    )
    try:
        assert await client._get(path) == stale_payload
    finally:
        await client.aclose()

    assert transport.request_count == 1
