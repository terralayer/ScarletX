from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import shutil
import sqlite3
import statistics
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


LIST_SCENES = 1_000
LIBRARY_FILES = 10_000
QUEUE_JOBS = 200
TPDB_CONCURRENT_READS = 100
PROGRESS_UPDATES = 1_000
PROGRESS_BYTES_PER_UPDATE = 4 * 1024
PROGRESS_DURATION_SECONDS = 10.0
IDLE_UI_SESSION_SECONDS = 600
IDLE_UI_PUBLISHER_EVENTS = 10_000
IDLE_UI_FALLBACK_INTERVAL_SECONDS = 15


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    iterations: int
    elapsed_seconds: float
    operations: int
    metadata: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["scenario"] = payload.pop("name")
        payload["operations_per_second"] = (
            self.operations / self.elapsed_seconds if self.elapsed_seconds > 0 else None
        )
        return payload


@contextmanager
def _isolated_scarletx_environment(temp_root: Path) -> Iterator[None]:
    replacements = {
        "SCARLETX_DATABASE_URL": f"sqlite:///{temp_root / 'global.sqlite3'}",
        "SCARLETX_CACHE_DIR": str(temp_root / "cache"),
        "SCARLETX_GENERATED_DIR": str(temp_root / "generated"),
    }
    previous = {key: os.environ.get(key) for key in replacements}
    os.environ.update(replacements)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-16384")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA mmap_size=134217728")
    cursor.close()


def _session_factory(database_path: Path):
    from scarletx.db import Base

    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
    )
    event.listen(engine, "connect", _configure_sqlite)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _filesystem_details(temp_root: Path) -> dict[str, object]:
    filesystem: dict[str, object] = {"path": str(temp_root.resolve())}
    try:
        stat = os.statvfs(temp_root)
        filesystem["block_size"] = stat.f_frsize
    except (AttributeError, OSError):
        pass

    mounts = Path("/proc/mounts")
    if mounts.exists():
        try:
            target = str(temp_root.resolve())
            candidates: list[tuple[int, str, str, str]] = []
            for line in mounts.read_text().splitlines():
                parts = line.split()
                if len(parts) < 3:
                    continue
                mount = parts[1].replace("\\040", " ")
                if target == mount or target.startswith(mount.rstrip("/") + "/"):
                    candidates.append((len(mount), parts[0], parts[2], mount))
            if candidates:
                _, device, filesystem_type, mount = max(candidates)
                filesystem.update({"device": device, "type": filesystem_type, "mount": mount})
        except OSError:
            pass
    return filesystem


def _environment(temp_root: Path) -> dict[str, object]:
    return {
        "cpu_count": os.cpu_count(),
        "processor": platform.processor() or platform.machine(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "filesystem": _filesystem_details(temp_root),
    }


def _seed_list_api(session_factory, temp_root: Path, count: int = LIST_SCENES) -> None:
    from scarletx.models import MediaFile, Performer, Scene, Studio

    started = datetime(2026, 1, 1, tzinfo=UTC)
    studios = [Studio(tpdb_id=f"studio-{index:03d}", name=f"Studio {index:03d}") for index in range(20)]
    performers = [
        Performer(tpdb_id=f"performer-{index:03d}", name=f"Performer {index:03d}", is_library=True)
        for index in range(40)
    ]
    with session_factory() as db:
        db.add_all(studios + performers)
        db.flush()
        scenes = []
        for index in range(count):
            scene = Scene(
                tpdb_id=f"scene-{index:05d}",
                title=f"Benchmark Scene {index:05d}",
                content_type="scene",
                studio=studios[index % len(studios)],
                imported_at=started + timedelta(seconds=index),
            )
            scene.performers.extend(
                [performers[index % len(performers)], performers[(index + 7) % len(performers)]]
            )
            scenes.append(scene)
        db.add_all(scenes)
        db.flush()
        db.add_all(
            [
                MediaFile(
                    scene_id=scene.id,
                    path=str(temp_root / "logical-media" / f"{scene.id}.mp4"),
                    size_bytes=1_000_000_000,
                    quality="1080p",
                    release_title=scene.title,
                )
                for scene in scenes[::2]
            ]
        )
        db.commit()


def _get_route_endpoint(app, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set()):
            return route.endpoint
    raise RuntimeError(f"FastAPI route not found: {path}")


def _benchmark_list_api(temp_root: Path, iterations: int) -> BenchmarkResult:
    from scarletx.main import app

    engine, session_factory = _session_factory(temp_root / "list-api.sqlite3")
    try:
        _seed_list_api(session_factory, temp_root)
        endpoint = _get_route_endpoint(app, "/api/library/scenes/page")
        samples: list[float] = []
        operation_count = 0
        for _ in range(iterations):
            started = time.perf_counter()
            with session_factory() as db:
                payload = endpoint(limit=100, offset=0, cursor=None, q=None, db=db)
            samples.append(time.perf_counter() - started)
            operation_count = len(payload["items"])
        return BenchmarkResult(
            "list_api",
            iterations,
            statistics.median(samples),
            operation_count,
            {
                "fixture_scenes": LIST_SCENES,
                "page_size": 100,
                "samples_seconds": samples,
            },
        )
    finally:
        engine.dispose()


def _create_library_fixture(root: Path, count: int = LIBRARY_FILES) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        directory = root / f"group-{index // 100:03d}"
        directory.mkdir(exist_ok=True)
        (directory / f"benchmark-{index:05d}.mp4").touch()


def _benchmark_library_scan(temp_root: Path, iterations: int) -> BenchmarkResult:
    from scarletx.media_library import scan_library
    from scarletx.models import RootFolder

    library_root = temp_root / "library"
    _create_library_fixture(library_root)
    engine, session_factory = _session_factory(temp_root / "library-scan.sqlite3")
    try:
        with session_factory() as db:
            db.add(
                RootFolder(
                    name="Benchmark Scenes",
                    content_type="scene",
                    path=str(library_root),
                    is_default=True,
                )
            )
            db.commit()
        warmup = scan_library(session_factory)
        samples: list[float] = []
        last_scan: dict[str, int] = {}
        for _ in range(iterations):
            started = time.perf_counter()
            last_scan = scan_library(session_factory)
            samples.append(time.perf_counter() - started)
        return BenchmarkResult(
            "library_scan",
            iterations,
            statistics.median(samples),
            last_scan.get("files", 0),
            {
                "fixture_files": LIBRARY_FILES,
                "fixture_directories": (LIBRARY_FILES + 99) // 100,
                "warmup": warmup,
                "last_scan": last_scan,
                "unchanged_expensive_probes": last_scan.get("indexed", 0) + last_scan.get("unmatched", 0),
                "samples_seconds": samples,
            },
        )
    finally:
        engine.dispose()


def _seed_queue(session_factory, count: int = QUEUE_JOBS) -> None:
    from scarletx.models import NativeUsenetJob

    started = datetime(2026, 1, 1, tzinfo=UTC)
    states = ("queued", "downloading", "paused", "postprocessing")
    with session_factory() as db:
        db.add_all(
            [
                NativeUsenetJob(
                    id=f"benchmark-{index:04d}",
                    title=f"Benchmark Job {index:04d}",
                    nzb_url=f"https://invalid.local/{index:04d}.nzb",
                    status=states[index % len(states)],
                    total_bytes=1_000_000_000,
                    downloaded_bytes=index * 1_000_000,
                    speed_bps=25_000_000.0,
                    eta_seconds=40,
                    created_at=started + timedelta(seconds=index),
                )
                for index in range(count)
            ]
        )
        db.commit()


def _measure_progress_checkpoint_writes(engine, session_factory) -> dict[str, object]:
    from scarletx import native_usenet
    from scarletx.models import NativeUsenetJob

    job_id = "benchmark-progress-checkpoints"
    with session_factory() as db:
        db.add(
            NativeUsenetJob(
                id=job_id,
                title="Progress checkpoint benchmark",
                nzb_url="https://invalid.local/progress.nzb",
                status="completed",
                total_bytes=64 * 1024 * 1024,
                downloaded_bytes=0,
                speed_bps=0.0,
            )
        )
        db.commit()

    writes = 0

    def count_progress_updates(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal writes
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update native_usenet_jobs set"):
            writes += 1

    event.listen(engine, "before_cursor_execute", count_progress_updates)
    native_usenet._clear_live_progress(job_id)
    gate = native_usenet._PROGRESS_CHECKPOINT_GATE
    gate.clear(job_id)
    original_monotonic = native_usenet.time.monotonic
    clock = [100.0]
    native_usenet.time.monotonic = lambda: clock[0]
    try:
        for index in range(PROGRESS_UPDATES):
            clock[0] = 100.0 + index * (PROGRESS_DURATION_SECONDS / PROGRESS_UPDATES)
            native_usenet._publish_progress(
                session_factory,
                job_id,
                total_bytes=64 * 1024 * 1024,
                downloaded_bytes=(index + 1) * PROGRESS_BYTES_PER_UPDATE,
                speed_bps=PROGRESS_BYTES_PER_UPDATE * PROGRESS_UPDATES / PROGRESS_DURATION_SECONDS,
                eta_seconds=1,
            )
    finally:
        native_usenet.time.monotonic = original_monotonic
        event.remove(engine, "before_cursor_execute", count_progress_updates)
        native_usenet._clear_live_progress(job_id)

    return {
        "updates": PROGRESS_UPDATES,
        "duration_seconds": PROGRESS_DURATION_SECONDS,
        "bytes_per_update": PROGRESS_BYTES_PER_UPDATE,
        "checkpoint_writes": writes,
    }


def _benchmark_queue_reads(temp_root: Path, iterations: int) -> BenchmarkResult:
    from scarletx.native_usenet import queue_rows

    engine, session_factory = _session_factory(temp_root / "queue.sqlite3")
    try:
        _seed_queue(session_factory)
        progress_checkpoint = _measure_progress_checkpoint_writes(engine, session_factory)
        samples: list[float] = []
        operation_count = 0
        for _ in range(iterations):
            started = time.perf_counter()
            with session_factory() as db:
                rows = queue_rows(db, limit=QUEUE_JOBS)
            samples.append(time.perf_counter() - started)
            operation_count = len(rows)
        return BenchmarkResult(
            "queue_reads",
            iterations,
            statistics.median(samples),
            operation_count,
            {
                "fixture_jobs": QUEUE_JOBS,
                "progress_checkpoint": progress_checkpoint,
                "samples_seconds": samples,
            },
        )
    finally:
        engine.dispose()


class _CountingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.request_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.request_count += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={"data": {"id": "benchmark"}}, request=request)


async def _one_tpdb_sample(cache_root: Path, sample_index: int) -> tuple[float, int]:
    from scarletx.tpdb import ThePornDBClient

    shutil.rmtree(cache_root, ignore_errors=True)
    transport = _CountingTransport()
    client = ThePornDBClient(
        api_key="",
        base_url="https://benchmark.invalid",
        transport=transport,
        max_retries=1,
    )
    started = time.perf_counter()
    try:
        await asyncio.gather(
            *(
                client._get(f"/scenes/benchmark-{sample_index}")
                for _ in range(TPDB_CONCURRENT_READS)
            )
        )
    finally:
        await client.aclose()
    return time.perf_counter() - started, transport.request_count


def _benchmark_tpdb_coalescing(temp_root: Path, iterations: int) -> BenchmarkResult:
    from scarletx import tpdb

    cache_root = temp_root / "tpdb-cache"
    original_cache_root = tpdb.TPDB_CACHE_ROOT
    tpdb.TPDB_CACHE_ROOT = cache_root
    try:
        samples: list[float] = []
        network_calls: list[int] = []
        for sample_index in range(iterations):
            elapsed, calls = asyncio.run(_one_tpdb_sample(cache_root, sample_index))
            samples.append(elapsed)
            network_calls.append(calls)
        return BenchmarkResult(
            "tpdb_coalescing",
            iterations,
            statistics.median(samples),
            TPDB_CONCURRENT_READS,
            {
                "concurrent_reads": TPDB_CONCURRENT_READS,
                "network_calls": network_calls,
                "samples_seconds": samples,
            },
        )
    finally:
        tpdb.TPDB_CACHE_ROOT = original_cache_root
        shutil.rmtree(cache_root, ignore_errors=True)


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

Scenario = Callable[[Path, int], BenchmarkResult]
SCENARIOS: dict[str, Scenario] = {
    "idle_ui": _benchmark_idle_ui,
    "list_api": _benchmark_list_api,
    "library_scan": _benchmark_library_scan,
    "queue_reads": _benchmark_queue_reads,
    "tpdb_coalescing": _benchmark_tpdb_coalescing,
}


def run_scenario(name: str, iterations: int, temp_root: Path) -> BenchmarkResult:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown benchmark scenario: {name}")
    return SCENARIOS[name](temp_root, iterations)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ScarletX 0.3.10 deterministic benchmark harness")
    parser.add_argument("--scenario", choices=[*sorted(SCENARIOS), "all"], required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1")

    with TemporaryDirectory(prefix="scarletx-0310-") as temporary:
        temp_root = Path(temporary)
        with _isolated_scarletx_environment(temp_root):
            if args.scenario == "all":
                results = [run_scenario(name, args.iterations, temp_root) for name in SCENARIOS]
                payload: dict[str, object] = {
                    "scenario": "all",
                    "iterations": args.iterations,
                    "results": [result.as_dict() for result in results],
                    "environment": _environment(temp_root),
                }
            else:
                result = run_scenario(args.scenario, args.iterations, temp_root)
                payload = result.as_dict()
                payload["environment"] = _environment(temp_root)

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
