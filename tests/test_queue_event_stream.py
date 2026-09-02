from __future__ import annotations

import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_INDEX = ROOT / "frontend" / "index.html"
FRONTEND_AUTH = ROOT / "frontend" / "auth.js"
MAIN = ROOT / "scarletx" / "main.py"


def _broker_class():
    from scarletx.event_stream import QueueEventBroker

    return QueueEventBroker


@pytest.mark.asyncio
async def test_reconnect_replays_events_after_last_id():
    QueueEventBroker = _broker_class()
    broker = QueueEventBroker(replay_size=8, subscriber_size=4)

    first = broker.publish("progress", {"job_id": "a", "downloaded_bytes": 1})
    second = broker.publish(
        "transition",
        {"job_id": "a", "status": "completed"},
    )

    replayed = [event async for event in broker.subscribe(first.id, take=1)]

    assert [event.id for event in replayed] == [second.id]
    assert replayed[0].kind == "transition"


@pytest.mark.asyncio
async def test_replay_window_miss_requests_one_resync():
    QueueEventBroker = _broker_class()
    broker = QueueEventBroker(replay_size=2, subscriber_size=4)

    broker.publish("progress", {"value": 1})
    broker.publish("progress", {"value": 2})
    broker.publish("progress", {"value": 3})

    events = [event async for event in broker.subscribe(0, take=1)]

    assert len(events) == 1
    assert events[0].kind == "resync"
    assert events[0].payload == {"reason": "replay_window_miss"}


@pytest.mark.asyncio
async def test_slow_subscriber_cannot_block_publisher():
    QueueEventBroker = _broker_class()
    broker = QueueEventBroker(replay_size=512, subscriber_size=4)
    subscriber = broker.subscribe(None)

    started = time.perf_counter()
    for index in range(1_000):
        broker.publish("progress", {"value": index})
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert broker.snapshot()["resync_required"] is True
    await subscriber.aclose()


@pytest.mark.asyncio
async def test_subscribers_are_isolated_and_disconnect_cleanup_is_immediate():
    QueueEventBroker = _broker_class()
    broker = QueueEventBroker(replay_size=16, subscriber_size=4)
    first = broker.subscribe(None)
    second = broker.subscribe(None)

    assert broker.snapshot()["subscriber_count"] == 2

    published = broker.publish("progress", {"job_id": "a", "progress": 12.5})
    first_event = await anext(first)
    second_event = await anext(second)

    assert first_event.id == published.id
    assert second_event.id == published.id

    await first.aclose()
    assert broker.snapshot()["subscriber_count"] == 1
    await second.aclose()
    assert broker.snapshot()["subscriber_count"] == 0


def test_event_ids_are_monotonic_and_event_kinds_are_typed():
    QueueEventBroker = _broker_class()
    broker = QueueEventBroker()

    kinds = ("snapshot", "progress", "transition", "history", "resync")
    events = [broker.publish(kind, {"value": index}) for index, kind in enumerate(kinds)]

    assert [event.id for event in events] == [1, 2, 3, 4, 5]
    assert [event.kind for event in events] == list(kinds)
    with pytest.raises(ValueError, match="event kind"):
        broker.publish("unknown", {})


def test_event_payload_rejects_secret_bearing_fields():
    QueueEventBroker = _broker_class()
    broker = QueueEventBroker()

    for payload in (
        {"password": "do-not-stream"},
        {"api_key": "do-not-stream"},
        {"authorization": "Bearer do-not-stream"},
        {"nested": {"setup_token": "do-not-stream"}},
    ):
        with pytest.raises(ValueError, match="secret"):
            broker.publish("progress", payload)


def test_stream_route_uses_last_event_id_and_no_per_client_database_poll_loop():
    source = MAIN.read_text(encoding="utf-8")
    route_start = source.index('@app.get("/api/activity/stream")')
    route = source[route_start : route_start + 2_500]

    assert 'request.headers.get("last-event-id")' in route.casefold()
    assert "queue_event_broker.subscribe" in route
    assert "_load_cached_activity_queue_data" not in route
    assert "await asyncio.sleep(0.75)" not in route


def test_frontend_has_one_authenticated_global_eventsource():
    index = FRONTEND_INDEX.read_text(encoding="utf-8")
    auth = FRONTEND_AUTH.read_text(encoding="utf-8")
    constructor = "new EventSource('/api/activity/stream')"

    assert constructor not in index
    assert auth.count(constructor) == 1
    assert "scarletx:queue-event" in auth
    assert "scarletx:queue-event" in index


def test_frontend_rejects_duplicate_or_out_of_order_queue_deltas_by_event_id():
    auth = FRONTEND_AUTH.read_text(encoding="utf-8")

    assert "queueLastEventId" in auth
    assert "eventId <= state.queueLastEventId" in auth
    assert "kind !== 'resync'" in auth
    assert "state.queueLastEventId = eventId" in auth


def test_healthy_sse_path_uses_events_not_recurring_queue_polling():
    index = FRONTEND_INDEX.read_text(encoding="utf-8")
    auth = FRONTEND_AUTH.read_text(encoding="utf-8")

    assert "scarletx:queue-stream-fallback" in auth
    assert "scarletx:queue-stream-fallback" in index
    assert "source.onopen" in auth
    assert "source.onerror" in auth
    assert "setTimeout(refreshLiveQueue,1000)" not in index
    assert "setTimeout(refreshLiveQueue,750)" not in index
