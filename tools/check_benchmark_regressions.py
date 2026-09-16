from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_SCENARIOS = frozenset(
    {
        "download_pipeline",
        "idle_ui",
        "list_api",
        "library_scan",
        "queue_reads",
        "tpdb_coalescing",
    }
)
TIMING_CEILINGS_SECONDS = {
    "download_pipeline": 3.0,
    "idle_ui": 1.0,
    "list_api": 1.0,
    "library_scan": 10.0,
    "queue_reads": 1.0,
    "tpdb_coalescing": 1.0,
}


def _failure(failures: list[str], field: str, actual: Any, expected: str) -> None:
    failures.append(f"{field}: got {actual!r}; expected {expected}")


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("metadata")
    return value if isinstance(value, dict) else {}


def check_benchmark_payload(payload: dict[str, Any]) -> list[str]:
    """Return stable regression failures for one benchmark-suite JSON payload."""
    failures: list[str] = []
    results = payload.get("results")
    if not isinstance(results, list):
        return ["results: benchmark payload must contain a results list"]

    by_name = {
        str(item.get("scenario")): item
        for item in results
        if isinstance(item, dict) and item.get("scenario")
    }
    missing = sorted(EXPECTED_SCENARIOS.difference(by_name))
    if missing:
        _failure(failures, "scenarios", missing, "all required benchmark scenarios")

    for name, ceiling in TIMING_CEILINGS_SECONDS.items():
        item = by_name.get(name)
        if item is None:
            continue
        elapsed = item.get("elapsed_seconds")
        if not isinstance(elapsed, (int, float)) or elapsed > ceiling:
            _failure(failures, f"{name}.elapsed_seconds", elapsed, f"<= {ceiling}")

    download = by_name.get("download_pipeline")
    if download is not None:
        meta = _metadata(download)
        if download.get("operations") != 10_000:
            _failure(failures, "download_pipeline.operations", download.get("operations"), "10000")
        if meta.get("api_rows") != 200:
            _failure(failures, "download_pipeline.api_rows", meta.get("api_rows"), "200")
        peak = meta.get("peak_buffer_size")
        maximum = meta.get("max_buffer_size")
        if not isinstance(peak, int) or not isinstance(maximum, int) or peak > maximum or peak > 8:
            _failure(failures, "download_pipeline.peak_buffer_size", peak, "<= max_buffer_size and <= 8")
        phases = set(meta.get("phase_names") or [])
        if not {"receive", "decode_write"}.issubset(phases):
            _failure(failures, "download_pipeline.phase_names", sorted(phases), "receive and decode_write")
        api_probe = meta.get("api_probe_seconds")
        if not isinstance(api_probe, (int, float)) or api_probe > 0.5:
            _failure(failures, "download_pipeline.api_probe_seconds", api_probe, "<= 0.5")

    idle = by_name.get("idle_ui")
    if idle is not None:
        meta = _metadata(idle)
        expected_values = {
            "global_eventsource_count": 1,
            "view_eventsource_count": 0,
            "recurring_queue_poll_markers": 0,
            "healthy_sse_queue_requests": 0,
            "subscriber_count_after_cleanup": 0,
        }
        for field, expected in expected_values.items():
            if meta.get(field) != expected:
                _failure(failures, f"idle_ui.{field}", meta.get(field), str(expected))
        replay_size = meta.get("replay_size")
        if not isinstance(replay_size, int) or replay_size > 512:
            _failure(failures, "idle_ui.replay_size", replay_size, "<= 512")
        subscriber_size = meta.get("subscriber_queue_size")
        if not isinstance(subscriber_size, int) or subscriber_size > 64:
            _failure(failures, "idle_ui.subscriber_queue_size", subscriber_size, "<= 64")

    list_api = by_name.get("list_api")
    if list_api is not None:
        meta = _metadata(list_api)
        if list_api.get("operations") != 100:
            _failure(failures, "list_api.operations", list_api.get("operations"), "100")
        if meta.get("fixture_scenes") != 1000:
            _failure(failures, "list_api.fixture_scenes", meta.get("fixture_scenes"), "1000")
        if meta.get("page_size") != 100:
            _failure(failures, "list_api.page_size", meta.get("page_size"), "100")

    scan = by_name.get("library_scan")
    if scan is not None:
        meta = _metadata(scan)
        last_scan = meta.get("last_scan") if isinstance(meta.get("last_scan"), dict) else {}
        if scan.get("operations") != 10_000:
            _failure(failures, "library_scan.operations", scan.get("operations"), "10000")
        if meta.get("unchanged_expensive_probes") != 0:
            _failure(
                failures,
                "library_scan.unchanged_expensive_probes",
                meta.get("unchanged_expensive_probes"),
                "0",
            )
        if last_scan.get("files") != 10_000:
            _failure(failures, "library_scan.last_scan.files", last_scan.get("files"), "10000")
        if last_scan.get("skipped") != 10_000:
            _failure(failures, "library_scan.last_scan.skipped", last_scan.get("skipped"), "10000")
        if last_scan.get("errors") != 0:
            _failure(failures, "library_scan.last_scan.errors", last_scan.get("errors"), "0")

    queue = by_name.get("queue_reads")
    if queue is not None:
        meta = _metadata(queue)
        progress = meta.get("progress_checkpoint") if isinstance(meta.get("progress_checkpoint"), dict) else {}
        if queue.get("operations") != 200:
            _failure(failures, "queue_reads.operations", queue.get("operations"), "200")
        if meta.get("fixture_jobs") != 200:
            _failure(failures, "queue_reads.fixture_jobs", meta.get("fixture_jobs"), "200")
        if progress.get("updates") != 1000:
            _failure(failures, "queue_reads.progress_checkpoint.updates", progress.get("updates"), "1000")
        writes = progress.get("checkpoint_writes")
        if not isinstance(writes, int) or writes > 10:
            _failure(failures, "queue_reads.progress_checkpoint.checkpoint_writes", writes, "<= 10")

    tpdb = by_name.get("tpdb_coalescing")
    if tpdb is not None:
        meta = _metadata(tpdb)
        if tpdb.get("operations") != 100:
            _failure(failures, "tpdb_coalescing.operations", tpdb.get("operations"), "100")
        if meta.get("concurrent_reads") != 100:
            _failure(failures, "tpdb_coalescing.concurrent_reads", meta.get("concurrent_reads"), "100")
        calls = meta.get("network_calls")
        if not isinstance(calls, list) or not calls or any(call != 1 for call in calls):
            _failure(failures, "tpdb_coalescing.network_calls", calls, "one network call per sample")

    return failures


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check ScarletX benchmark regression budgets")
    parser.add_argument("benchmark_json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = json.loads(args.benchmark_json.read_text(encoding="utf-8"))
    failures = check_benchmark_payload(payload)
    if failures:
        print("Benchmark regression gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Benchmark regression gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
