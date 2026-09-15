from __future__ import annotations

import pytest


def test_replay_window_miss_forces_resync():
    from scarletx.event_stream import QueueEventBroker

    broker = QueueEventBroker(replay_size=3, subscriber_size=3)
    for index in range(5):
        broker.publish("progress", {"job": {"id": index}})

    subscription = broker.subscribe(1)
    assert subscription._queue.qsize() == 1
    event = subscription._queue.get_nowait()
    assert event.kind == "resync"
    assert event.payload == {"reason": "replay_window_miss"}


def test_slow_subscriber_is_bounded_and_forced_to_resync():
    from scarletx.event_stream import QueueEventBroker

    broker = QueueEventBroker(replay_size=8, subscriber_size=2)
    subscription = broker.subscribe(None)
    broker.publish("progress", {"job": {"id": 1}})
    broker.publish("progress", {"job": {"id": 2}})
    broker.publish("progress", {"job": {"id": 3}})

    assert subscription._queue.qsize() == 1
    event = subscription._queue.get_nowait()
    assert event.kind == "resync"
    assert event.payload == {"reason": "subscriber_overflow"}


def test_event_payloads_reject_nested_secrets():
    from scarletx.event_stream import QueueEventBroker

    broker = QueueEventBroker()
    with pytest.raises(ValueError, match="secret"):
        broker.publish("progress", {"job": {"provider_password": "never-store-this"}})
