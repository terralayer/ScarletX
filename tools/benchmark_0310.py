from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
from tempfile import TemporaryDirectory
import time
from typing import Callable

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import NativeUsenetJob
from scarletx.native_usenet import queue_rows


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


def _environment(temp_root: Path) -> dict[str, object]:
    filesystem: dict[str, object] = {"path": str(temp_root.resolve())}
    try:
        stat = os.statvfs(temp_root)
        filesystem["block_size"] = stat.f_frsize
    except (AttributeError, OSError):
        pass
    return {
        "cpu_count": os.cpu_count(),
        "processor": platform.processor() or platform.machine(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "sqlite_version": sqlite3.sqlite_version,
        "filesystem": filesystem,
    }


def _seed_queue(session_factory, count: int = 200) -> None:
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


def _benchmark_queue_reads(temp_root: Path, iterations: int) -> BenchmarkResult:
    engine, session_factory = _session_factory(temp_root / "queue.sqlite3")
    try:
        _seed_queue(session_factory)
        samples: list[float] = []
        operation_count = 0
        for _ in range(iterations):
            started = time.perf_counter()
            with session_factory() as db:
                rows = queue_rows(db, limit=200)
            samples.append(time.perf_counter() - started)
            operation_count = len(rows)
        median = statistics.median(samples)
        return BenchmarkResult(
            "queue_reads",
            iterations,
            median,
            operation_count,
            {"fixture_jobs": 200, "samples_seconds": samples},
        )
    finally:
        engine.dispose()


Scenario = Callable[[Path, int], BenchmarkResult]
SCENARIOS: dict[str, Scenario] = {"queue_reads": _benchmark_queue_reads}


def run_scenario(name: str, iterations: int, temp_root: Path) -> BenchmarkResult:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown benchmark scenario: {name}")
    return SCENARIOS[name](temp_root, iterations)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ScarletX 0.3.10 deterministic benchmark harness")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.iterations < 1:
        raise SystemExit("--iterations must be at least 1")

    with TemporaryDirectory(prefix="scarletx-0310-") as temporary:
        temp_root = Path(temporary)
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
