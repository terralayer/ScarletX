from __future__ import annotations

import threading
import time


def test_processing_concurrency_defaults_to_one(monkeypatch):
    from scarletx.config import Settings

    monkeypatch.delenv("SCARLETX_USENET_CONCURRENT_PROCESSING", raising=False)
    settings = Settings()
    assert settings.native_usenet_concurrent_downloads == 2
    assert settings.native_usenet_concurrent_processing == 1


def test_processing_capacity_is_independent_and_bounded():
    from scarletx.usenet.processing_capacity import _SharedProcessingCapacity

    capacity = _SharedProcessingCapacity(1)
    active = 0
    peak = 0
    lock = threading.Lock()
    start = threading.Barrier(4)

    def work():
        nonlocal active, peak
        start.wait()
        with capacity.slot():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1

    threads = [threading.Thread(target=work) for _ in range(3)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=1)

    assert peak == 1
    assert capacity.limit == 1


def test_scheduler_keeps_network_capacity_when_one_job_is_processing():
    from scarletx.usenet.scheduler import _network_capacity

    statuses = {
        "download-a": "downloading",
        "processing-b": "postprocessing",
    }
    assert _network_capacity(statuses, download_limit=2) == 1

    statuses["download-c"] = "downloading"
    assert _network_capacity(statuses, download_limit=2) == 0
