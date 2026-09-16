from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from scarletx.background_tasks import BackgroundTaskRegistry
from scarletx.event_stream import QueueEventBroker


async def _event_broker_stress(
    *, events: int, replay_size: int, subscriber_size: int
) -> dict[str, int | bool | str]:
    broker = QueueEventBroker(replay_size=replay_size, subscriber_size=subscriber_size)
    subscriber = broker.subscribe(None)
    try:
        for index in range(events):
            broker.publish(
                "progress",
                {"job": {"external_id": "stress-job", "progress": index}},
            )
        first_event = await subscriber.__anext__()
        snapshot = broker.snapshot()
    finally:
        await subscriber.aclose()

    return {
        "events": events,
        "last_event_id": int(snapshot["last_event_id"]),
        "replay_count": int(snapshot["replay_count"]),
        "replay_size": int(snapshot["replay_size"]),
        "subscriber_size": int(snapshot["subscriber_size"]),
        "resync_required": bool(snapshot["resync_required"]),
        "first_event_kind": first_event.kind,
        "subscriber_count_after_cleanup": int(broker.snapshot()["subscriber_count"]),
    }


def run_event_broker_stress(
    *, events: int = 10_000, replay_size: int = 512, subscriber_size: int = 64
) -> dict[str, int | bool | str]:
    if events < 1:
        raise ValueError("events must be positive")
    return asyncio.run(
        _event_broker_stress(
            events=events,
            replay_size=replay_size,
            subscriber_size=subscriber_size,
        )
    )


async def _background_task_stress(*, tasks: int, batch_size: int) -> dict[str, object]:
    registry = BackgroundTaskRegistry(max_tasks=batch_size, failure_limit=8)
    peak_active = 0

    async def worker() -> None:
        await asyncio.sleep(0)

    for start in range(0, tasks, batch_size):
        count = min(batch_size, tasks - start)
        batch = [registry.create_task(worker(), name=f"stress-{start + index}") for index in range(count)]
        peak_active = max(peak_active, registry.active_count)
        await asyncio.gather(*batch)
        await asyncio.sleep(0)

    result = {
        "tasks": tasks,
        "batch_size": batch_size,
        "peak_active": peak_active,
        "active_after_cleanup": registry.active_count,
        "failures": registry.failures,
    }
    await registry.shutdown()
    return result


def run_background_task_stress(*, tasks: int = 2_000, batch_size: int = 32) -> dict[str, object]:
    if tasks < 1:
        raise ValueError("tasks must be positive")
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    return asyncio.run(_background_task_stress(tasks=tasks, batch_size=batch_size))


def run_stress_suite(*, events: int, tasks: int, batch_size: int) -> dict[str, object]:
    return {
        "event_broker": run_event_broker_stress(events=events),
        "background_tasks": run_background_task_stress(tasks=tasks, batch_size=batch_size),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ScarletX deterministic reliability stress suite")
    parser.add_argument("--events", type=int, default=25_000)
    parser.add_argument("--tasks", type=int, default=5_000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--json", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = run_stress_suite(events=args.events, tasks=args.tasks, batch_size=args.batch_size)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
