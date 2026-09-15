from __future__ import annotations

import json
import os
import time

import httpx
import pytest


@pytest.mark.asyncio
async def test_stale_tpdb_fallback_is_counted_as_disk_cache_hit(tmp_path, monkeypatch):
    from scarletx import tpdb
    from scarletx.async_cache import AsyncLRUCache
    from scarletx.observability import RuntimeObservability

    metrics = RuntimeObservability()
    monkeypatch.setattr(tpdb, "runtime_observability", metrics)
    monkeypatch.setattr(tpdb, "TPDB_CACHE_ROOT", tmp_path / "tpdb")
    monkeypatch.setattr(tpdb, "_TPDB_MEMORY_CACHE", AsyncLRUCache(max_entries=8))

    path = "/scenes/stale-section-4"
    cache_path = tpdb._cache_key(path, None)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"data": {"id": "stale"}}))
    old = time.time() - 172800
    os.utime(cache_path, (old, old))

    async def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"}, request=request)

    client = tpdb.ThePornDBClient(
        api_key="",
        base_url="https://cache-section-4.invalid",
        transport=httpx.MockTransport(unavailable),
        max_retries=1,
    )
    try:
        assert await client._get(path) == {"data": {"id": "stale"}}
    finally:
        await client.aclose()

    snapshot = metrics.snapshot()["tpdb"]
    assert snapshot["network_requests"] == 1
    assert snapshot["network_failures"] == 1
    assert snapshot["cache_hits"]["disk"] == 1
