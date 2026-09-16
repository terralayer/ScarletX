from __future__ import annotations

from pathlib import Path

from tools.stress_reliability import run_background_task_stress, run_event_broker_stress


def test_event_broker_stress_stays_bounded_and_forces_resync():
    result = run_event_broker_stress(events=10_000, replay_size=512, subscriber_size=64)

    assert result["events"] == 10_000
    assert result["last_event_id"] == 10_000
    assert result["replay_count"] == 512
    assert result["replay_size"] == 512
    assert result["subscriber_size"] == 64
    assert result["resync_required"] is True
    assert result["first_event_kind"] == "resync"
    assert result["subscriber_count_after_cleanup"] == 0


def test_background_task_stress_keeps_registry_bounded_and_drains():
    result = run_background_task_stress(tasks=2_000, batch_size=32)

    assert result["tasks"] == 2_000
    assert result["batch_size"] == 32
    assert result["peak_active"] <= 32
    assert result["active_after_cleanup"] == 0
    assert result["failures"] == []


def test_ci_runs_dedicated_reliability_stress_job():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml").read_text()

    assert "reliability-stress:" in workflow
    assert "Run bounded reliability stress suite" in workflow
    assert "python tools/stress_reliability.py" in workflow
    assert "--events 25000" in workflow
    assert "--tasks 5000" in workflow
