from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from typing import Any


EVENT_KINDS = frozenset({"snapshot", "progress", "transition", "history", "resync"})
_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "credentials",
        "password",
        "secret",
        "setup_token",
        "token",
    }
)


@dataclass(frozen=True, slots=True)
class QueueEvent:
    id: int
    kind: str
    payload: dict[str, Any]


class QueueSubscription(AsyncIterator[QueueEvent]):
    def __init__(
        self,
        broker: QueueEventBroker,
        subscriber_id: int,
        queue: asyncio.Queue[QueueEvent],
        *,
        take: int | None = None,
    ) -> None:
        self._broker = broker
        self._subscriber_id = subscriber_id
        self._queue = queue
        self._remaining = take
        self._closed = False
        self._needs_resync = False

    def __aiter__(self) -> QueueSubscription:
        return self

    async def __anext__(self) -> QueueEvent:
        if self._closed or self._remaining == 0:
            await self.aclose()
            raise StopAsyncIteration
        event = await self._queue.get()
        if event.kind == "resync":
            self._needs_resync = False
        if self._remaining is not None:
            self._remaining -= 1
        return event

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._broker._remove_subscriber(self._subscriber_id)

    def _enqueue(self, event: QueueEvent) -> bool:
        if self._closed:
            return True
        try:
            self._queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            return False

    def _force_resync(self, event: QueueEvent) -> None:
        if self._closed or self._needs_resync:
            return
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._needs_resync = True
        self._queue.put_nowait(event)


class QueueEventBroker:
    """Bounded in-process queue event fanout with replay and resynchronization."""

    def __init__(self, *, replay_size: int = 512, subscriber_size: int = 64) -> None:
        if replay_size < 1:
            raise ValueError("replay_size must be positive")
        if subscriber_size < 1:
            raise ValueError("subscriber_size must be positive")
        self.replay_size = replay_size
        self.subscriber_size = subscriber_size
        self._replay: deque[QueueEvent] = deque(maxlen=replay_size)
        self._subscribers: dict[int, QueueSubscription] = {}
        self._next_subscriber_id = 1
        self._last_event_id = 0
        self._resync_required = False

    def publish(self, kind: str, payload: Mapping[str, Any]) -> QueueEvent:
        if kind not in EVENT_KINDS:
            raise ValueError(f"unsupported event kind: {kind}")
        normalized = dict(payload)
        if _contains_secret_field(normalized):
            raise ValueError("queue event payload contains secret field")
        self._last_event_id += 1
        event = QueueEvent(self._last_event_id, kind, normalized)
        self._replay.append(event)
        if kind == "resync":
            self._resync_required = True
        for subscription in tuple(self._subscribers.values()):
            if subscription._enqueue(event):
                continue
            self._resync_required = True
            subscription._force_resync(self._resync_event("subscriber_overflow"))
        return event

    def subscribe(self, last_event_id: int | None, *, take: int | None = None) -> QueueSubscription:
        subscriber_id = self._next_subscriber_id
        self._next_subscriber_id += 1
        queue: asyncio.Queue[QueueEvent] = asyncio.Queue(maxsize=self.subscriber_size)
        subscription = QueueSubscription(self, subscriber_id, queue, take=take)
        self._subscribers[subscriber_id] = subscription

        if last_event_id is None:
            return subscription

        replay = tuple(self._replay)
        if last_event_id > self._last_event_id:
            self._resync_required = True
            subscription._force_resync(self._resync_event("future_event_id"))
            return subscription
        if replay and last_event_id < replay[0].id - 1:
            self._resync_required = True
            subscription._force_resync(self._resync_event("replay_window_miss"))
            return subscription

        missing = [event for event in replay if event.id > last_event_id]
        if len(missing) > self.subscriber_size:
            self._resync_required = True
            subscription._force_resync(self._resync_event("subscriber_overflow"))
            return subscription
        for event in missing:
            subscription._enqueue(event)
        return subscription

    def snapshot(self) -> dict[str, int | bool]:
        return {
            "last_event_id": self._last_event_id,
            "replay_count": len(self._replay),
            "subscriber_count": len(self._subscribers),
            "replay_size": self.replay_size,
            "subscriber_size": self.subscriber_size,
            "resync_required": self._resync_required,
        }

    def _resync_event(self, reason: str) -> QueueEvent:
        return QueueEvent(self._last_event_id, "resync", {"reason": reason})

    def _remove_subscriber(self, subscriber_id: int) -> None:
        self._subscribers.pop(subscriber_id, None)


queue_event_broker = QueueEventBroker(replay_size=512, subscriber_size=64)


def format_sse(event: QueueEvent) -> str:
    body = json.dumps(event.payload, default=str, separators=(",", ":"))
    return f"id:{event.id}\nevent:{event.kind}\ndata:{body}\n\n"


async def queue_event_pump(
    load_snapshot: Callable[[], dict[str, Any]],
    *,
    interval_seconds: float = 0.75,
    broker: QueueEventBroker = queue_event_broker,
) -> None:
    """Poll queue state once process-wide and publish only meaningful deltas."""
    previous: dict[str, dict[str, Any]] | None = None
    previous_order: tuple[str, ...] = ()
    while True:
        try:
            payload = await asyncio.to_thread(load_snapshot)
            rows = list(payload.get("tracked") or [])
            current = {str(row.get("external_id") or row.get("id")): row for row in rows}
            order = tuple(current)
            if previous is None or order != previous_order:
                broker.publish("snapshot", payload)
            else:
                for job_id in order:
                    row = current[job_id]
                    old = previous.get(job_id)
                    if old == row:
                        continue
                    old_status = (old or {}).get("client_status") or (old or {}).get("status")
                    new_status = row.get("client_status") or row.get("status")
                    kind = "transition" if old_status != new_status else "progress"
                    broker.publish(kind, {"job": row})
            previous = current
            previous_order = order
        except asyncio.CancelledError:
            raise
        except Exception:
            # A transient DB/read failure must not take down the event producer.
            pass
        await asyncio.sleep(interval_seconds)


def _contains_secret_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if normalized in _SECRET_KEYS or normalized.endswith("_password") or normalized.endswith("_secret"):
                return True
            if _contains_secret_field(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret_field(item) for item in value)
    return False
