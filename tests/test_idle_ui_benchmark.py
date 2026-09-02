from __future__ import annotations

import importlib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_idle_ui_benchmark_models_ten_minutes_without_healthy_queue_polling(tmp_path):
    benchmark = importlib.import_module("tools.benchmark_0310")

    assert "idle_ui" in benchmark.SCENARIOS
    result = benchmark.run_scenario("idle_ui", 1, tmp_path)
    metadata = result.metadata

    assert result.name == "idle_ui"
    assert metadata["modeled_session_seconds"] == 600
    assert metadata["healthy_sse_queue_requests"] == 0
    assert metadata["fallback_interval_seconds"] >= 15
    assert metadata["subscriber_queue_size"] == 64
    assert metadata["replay_size"] == 512
    assert metadata["publisher_events"] >= 1_000
    assert metadata["resync_required"] is True
    assert metadata["subscriber_count_after_cleanup"] == 0


def test_idle_ui_benchmark_requires_global_eventsource_and_no_healthy_poll_timer(tmp_path):
    benchmark = importlib.import_module("tools.benchmark_0310")
    result = benchmark.run_scenario("idle_ui", 1, tmp_path)
    metadata = result.metadata

    assert metadata["global_eventsource_count"] == 1
    assert metadata["view_eventsource_count"] == 0
    assert metadata["recurring_queue_poll_markers"] == 0
