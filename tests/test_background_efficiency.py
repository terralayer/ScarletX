import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_wake_signal_notifies_waiter_without_poll_delay():
    from scarletx.background_signals import AsyncWakeSignal

    signal = AsyncWakeSignal("test")
    await signal.bind()
    waiter = asyncio.create_task(signal.wait(5.0))
    await asyncio.sleep(0)
    signal.notify()
    assert await asyncio.wait_for(waiter, timeout=0.5) is True


@pytest.mark.asyncio
async def test_wake_signal_fallback_timeout_is_observable():
    from scarletx.background_signals import AsyncWakeSignal

    signal = AsyncWakeSignal("test")
    await signal.bind()
    assert await signal.wait(0.01) is False


def test_native_downloader_uses_signal_with_recovery_fallback():
    source = (ROOT / "scarletx" / "usenet" / "worker.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert "native_queue_signal.notify()" in compact
    assert "awaitnative_queue_signal.bind()" in compact
    assert "awaitnative_queue_signal.wait(NATIVE_QUEUE_RECOVERY_SECONDS)" in compact
    assert "NATIVE_QUEUE_RECOVERY_SECONDS=60" in compact


def test_completed_import_loop_uses_completion_signal_with_recovery_fallback():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert "awaitcompleted_import_signal.bind()" in compact
    assert "awaitcompleted_import_signal.wait(wait_seconds)" in compact
    assert "COMPLETED_IMPORT_RECOVERY_SECONDS=120" in compact


def test_native_completion_wakes_import_processor():
    source = (ROOT / "scarletx" / "usenet" / "worker.py").read_text(encoding="utf-8")
    assert "completed_import_signal.notify()" in source


def test_media_tools_are_capped_at_two_concurrent_processes():
    source = (ROOT / "scarletx" / "media_library.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert 'MEDIA_TOOL_CONCURRENCY=max(1,int(os.getenv("SCARLETX_MEDIA_TOOL_CONCURRENCY","2")))' in compact
    assert "_MEDIA_TOOL_SEMAPHORE=threading.BoundedSemaphore(MEDIA_TOOL_CONCURRENCY)" in compact
    assert "with_MEDIA_TOOL_SEMAPHORE:" in compact
    assert "workers=min(MEDIA_TOOL_CONCURRENCY,len(to_index))" in compact


def test_runtime_metrics_expose_background_efficiency_counters():
    from scarletx.runtime_metrics import runtime_metrics

    snapshot = runtime_metrics.snapshot()
    for key in (
        "native_queue_signal_wakes",
        "native_queue_fallback_wakes",
        "completed_import_signal_wakes",
        "completed_import_fallback_wakes",
        "media_tool_active",
        "media_tool_peak",
    ):
        assert key in snapshot
