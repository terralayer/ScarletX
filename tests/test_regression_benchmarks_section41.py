from __future__ import annotations

from pathlib import Path

from tools.check_benchmark_regressions import check_benchmark_payload


def good_payload() -> dict:
    return {
        "scenario": "all",
        "iterations": 5,
        "results": [
            {
                "scenario": "download_pipeline",
                "elapsed_seconds": 0.4,
                "operations": 10_000,
                "metadata": {
                    "api_probe_seconds": 0.01,
                    "api_rows": 200,
                    "max_buffer_size": 8,
                    "peak_buffer_size": 8,
                    "phase_names": ["decode_write", "receive"],
                    "workers": 4,
                },
            },
            {
                "scenario": "idle_ui",
                "elapsed_seconds": 0.1,
                "operations": 10_000,
                "metadata": {
                    "global_eventsource_count": 1,
                    "view_eventsource_count": 0,
                    "recurring_queue_poll_markers": 0,
                    "healthy_sse_queue_requests": 0,
                    "replay_size": 512,
                    "subscriber_queue_size": 64,
                    "subscriber_count_after_cleanup": 0,
                },
            },
            {
                "scenario": "list_api",
                "elapsed_seconds": 0.01,
                "operations": 100,
                "metadata": {"fixture_scenes": 1000, "page_size": 100},
            },
            {
                "scenario": "library_scan",
                "elapsed_seconds": 2.0,
                "operations": 10_000,
                "metadata": {
                    "fixture_files": 10_000,
                    "unchanged_expensive_probes": 0,
                    "last_scan": {"files": 10_000, "skipped": 10_000, "errors": 0},
                },
            },
            {
                "scenario": "queue_reads",
                "elapsed_seconds": 0.01,
                "operations": 200,
                "metadata": {
                    "fixture_jobs": 200,
                    "progress_checkpoint": {"updates": 1000, "checkpoint_writes": 5},
                },
            },
            {
                "scenario": "tpdb_coalescing",
                "elapsed_seconds": 0.02,
                "operations": 100,
                "metadata": {"concurrent_reads": 100, "network_calls": [1, 1, 1, 1, 1]},
            },
        ],
    }


def test_current_benchmark_shape_passes_regression_gate():
    assert check_benchmark_payload(good_payload()) == []


def test_structural_regressions_are_rejected():
    payload = good_payload()
    by_name = {item["scenario"]: item for item in payload["results"]}
    by_name["library_scan"]["metadata"]["unchanged_expensive_probes"] = 1
    by_name["queue_reads"]["metadata"]["progress_checkpoint"]["checkpoint_writes"] = 11
    by_name["tpdb_coalescing"]["metadata"]["network_calls"] = [1, 2, 1, 1, 1]
    by_name["idle_ui"]["metadata"]["recurring_queue_poll_markers"] = 1
    by_name["download_pipeline"]["metadata"]["peak_buffer_size"] = 9

    failures = check_benchmark_payload(payload)

    assert any("unchanged_expensive_probes" in item for item in failures)
    assert any("checkpoint_writes" in item for item in failures)
    assert any("network_calls" in item for item in failures)
    assert any("recurring_queue_poll_markers" in item for item in failures)
    assert any("peak_buffer_size" in item for item in failures)


def test_gross_timing_regressions_are_rejected_without_tight_flaky_limits():
    payload = good_payload()
    by_name = {item["scenario"]: item for item in payload["results"]}
    by_name["download_pipeline"]["elapsed_seconds"] = 3.01
    by_name["library_scan"]["elapsed_seconds"] = 10.01
    by_name["list_api"]["elapsed_seconds"] = 1.01

    failures = check_benchmark_payload(payload)

    assert any("download_pipeline.elapsed_seconds" in item for item in failures)
    assert any("library_scan.elapsed_seconds" in item for item in failures)
    assert any("list_api.elapsed_seconds" in item for item in failures)


def test_benchmark_ci_executes_regression_checker():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml").read_text()
    assert "Run benchmark regression gate" in workflow
    assert "python tools/check_benchmark_regressions.py /tmp/scarletx-0310-baseline.json" in workflow
