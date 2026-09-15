from __future__ import annotations

import threading
import time


def test_connection_budget_never_exceeds_global_limit():
    from scarletx.usenet.worker import _SharedConnectionBudget

    budget = _SharedConnectionBudget(2)
    active = 0
    peak = 0
    lock = threading.Lock()
    start = threading.Barrier(5)

    def run():
        nonlocal active, peak
        start.wait()
        with budget.slot():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with lock:
                active -= 1

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join(timeout=1)

    assert peak == 2
    assert budget.limit == 2


def test_shared_segment_fetcher_key_includes_global_connection_limit():
    from pydantic import SecretStr
    from scarletx.usenet import worker

    provider = worker.UsenetProviderConfig(
        name="primary",
        host="news.invalid",
        password=SecretStr("secret"),
        connections=20,
    )
    first = worker._provider_pool_key([provider], 2, 8)
    second = worker._provider_pool_key([provider], 2, 4)

    assert first != second
