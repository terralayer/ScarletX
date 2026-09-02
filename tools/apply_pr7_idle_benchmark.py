from __future__ import annotations

from pathlib import Path
from textwrap import dedent


BENCHMARK = Path("tools/benchmark_0310.py")
BASELINE_TEST = Path("tests/test_performance_baseline.py")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_benchmark() -> None:
    text = BENCHMARK.read_text(encoding="utf-8")

    constant_anchor = "PROGRESS_DURATION_SECONDS = 10.0\n"
    text = replace_once(
        text,
        constant_anchor,
        constant_anchor
        + "IDLE_UI_SESSION_SECONDS = 600\n"
        + "IDLE_UI_PUBLISHER_EVENTS = 10_000\n"
        + "IDLE_UI_FALLBACK_INTERVAL_SECONDS = 15\n",
        label="benchmark constants",
    )

    scenario_anchor = "\n\nScenario = Callable[[Path, int], BenchmarkResult]\n"
    implementation = dedent(
        '''

        async def _measure_idle_ui_sample() -> tuple[float, dict[str, int | bool]]:
            from scarletx.event_stream import QueueEventBroker

            broker = QueueEventBroker(replay_size=512, subscriber_size=64)
            subscriber = broker.subscribe(None)
            try:
                started = time.perf_counter()
                for index in range(IDLE_UI_PUBLISHER_EVENTS):
                    broker.publish(
                        "progress",
                        {
                            "job": {
                                "external_id": "idle-ui-benchmark",
                                "progress": index,
                            }
                        },
                    )
                elapsed = time.perf_counter() - started
                snapshot = broker.snapshot()
            finally:
                await subscriber.aclose()
            snapshot["subscriber_count_after_cleanup"] = broker.snapshot()["subscriber_count"]
            return elapsed, snapshot


        def _idle_ui_frontend_metrics() -> dict[str, int | str]:
            repo_root = Path(__file__).resolve().parents[1]
            auth_source = (repo_root / "frontend" / "auth.js").read_text(encoding="utf-8")
            index_source = (repo_root / "frontend" / "index.html").read_text(encoding="utf-8")
            eventsource = "new EventSource('/api/activity/stream')"
            recurring_markers = (
                "setInterval(()=>{if(view!=='activity')updateQueueBadge()",
                "setTimeout(refreshLiveQueue,1000)",
                "setTimeout(refreshLiveQueue,750)",
            )
            fallback_marker = "refreshLiveQueueFallback()},15000)"
            return {
                "measurement_kind": "modeled_control_flow",
                "global_eventsource_count": auth_source.count(eventsource),
                "view_eventsource_count": index_source.count(eventsource),
                "recurring_queue_poll_markers": sum(index_source.count(marker) for marker in recurring_markers),
                "fallback_interval_seconds": (
                    IDLE_UI_FALLBACK_INTERVAL_SECONDS if fallback_marker in index_source else 0
                ),
            }


        def _benchmark_idle_ui(temp_root: Path, iterations: int) -> BenchmarkResult:
            del temp_root
            frontend = _idle_ui_frontend_metrics()
            samples: list[float] = []
            last_snapshot: dict[str, int | bool] = {}
            for _ in range(iterations):
                elapsed, last_snapshot = asyncio.run(_measure_idle_ui_sample())
                samples.append(elapsed)

            healthy_queue_requests = 0 if (
                frontend["global_eventsource_count"] == 1
                and frontend["view_eventsource_count"] == 0
                and frontend["recurring_queue_poll_markers"] == 0
            ) else 1
            metadata: dict[str, object] = {
                **frontend,
                "modeled_session_seconds": IDLE_UI_SESSION_SECONDS,
                "healthy_sse_queue_requests": healthy_queue_requests,
                "publisher_events": IDLE_UI_PUBLISHER_EVENTS,
                "publisher_elapsed_seconds": statistics.median(samples),
                "samples_seconds": samples,
                "replay_size": last_snapshot.get("replay_size", 0),
                "subscriber_queue_size": last_snapshot.get("subscriber_size", 0),
                "resync_required": last_snapshot.get("resync_required", False),
                "subscriber_count_after_cleanup": last_snapshot.get(
                    "subscriber_count_after_cleanup", -1
                ),
            }
            return BenchmarkResult(
                "idle_ui",
                iterations,
                statistics.median(samples),
                IDLE_UI_PUBLISHER_EVENTS,
                metadata,
            )
        '''
    ).rstrip()
    text = replace_once(
        text,
        scenario_anchor,
        implementation + scenario_anchor,
        label="benchmark implementation",
    )

    mapping_anchor = 'SCENARIOS: dict[str, Scenario] = {\n    "list_api": _benchmark_list_api,\n'
    text = replace_once(
        text,
        mapping_anchor,
        'SCENARIOS: dict[str, Scenario] = {\n    "idle_ui": _benchmark_idle_ui,\n    "list_api": _benchmark_list_api,\n',
        label="scenario mapping",
    )
    BENCHMARK.write_text(text, encoding="utf-8")


def patch_baseline_test() -> None:
    text = BASELINE_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'EXPECTED_SCENARIOS = {"list_api", "library_scan", "queue_reads", "tpdb_coalescing"}',
        'EXPECTED_SCENARIOS = {"idle_ui", "list_api", "library_scan", "queue_reads", "tpdb_coalescing"}',
        label="expected scenarios",
    )
    assertion_anchor = '    assert results["list_api"]["operations"] == 100\n'
    idle_assertions = dedent(
        '''
            assert results["idle_ui"]["operations"] == 10_000
            assert results["idle_ui"]["metadata"]["modeled_session_seconds"] == 600
            assert results["idle_ui"]["metadata"]["healthy_sse_queue_requests"] == 0
            assert results["idle_ui"]["metadata"]["subscriber_queue_size"] == 64
            assert results["idle_ui"]["metadata"]["replay_size"] == 512
            assert len(results["idle_ui"]["metadata"]["samples_seconds"]) == 1

        '''
    )
    text = replace_once(
        text,
        assertion_anchor,
        idle_assertions + assertion_anchor,
        label="idle all-scenario assertions",
    )
    BASELINE_TEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_benchmark()
    patch_baseline_test()
