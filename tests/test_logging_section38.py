from __future__ import annotations

import io
import json

from scarletx.background_tasks import BackgroundTaskRegistry
from scarletx.runtime_logging import build_log_record, emit_structured_log


def test_structured_log_record_is_bounded_secret_safe_and_correlated():
    payload = build_log_record(
        "download_failed\nforged",
        level="ERROR",
        job_id="job-123",
        scene_id=42,
        detail="x" * 1000 + "\nnewline",
        api_key="super-secret",
        nested={"password": "hidden", "phase": "extracting"},
    )

    assert payload["event"] == "download_failed forged"
    assert payload["level"] == "ERROR"
    assert payload["job_id"] == "job-123"
    assert payload["scene_id"] == 42
    assert len(payload["detail"]) <= 256
    assert "\n" not in payload["detail"]
    assert payload["api_key"] == "[REDACTED]"
    assert payload["nested"]["password"] == "[REDACTED]"
    assert payload["nested"]["phase"] == "extracting"
    assert len(payload) <= 24


def test_emit_structured_log_writes_exactly_one_json_line():
    stream = io.StringIO()
    payload = emit_structured_log(
        "scene_search_completed",
        stream=stream,
        job_id="job-9",
        scene_id=77,
        status="queued",
    )

    output = stream.getvalue()
    assert output.endswith("\n")
    assert output.count("\n") == 1
    assert json.loads(output) == payload


def test_background_task_failures_emit_structured_metadata(monkeypatch):
    emitted: list[tuple[str, dict]] = []

    def capture(event: str, **fields):
        emitted.append((event, fields))
        return {"event": event, **fields}

    monkeypatch.setattr("scarletx.background_tasks.emit_structured_log", capture)
    registry = BackgroundTaskRegistry(max_tasks=2, failure_limit=2)

    class Boom(RuntimeError):
        pass

    async def fail():
        raise Boom("must never be logged: password=hunter2")

    async def run():
        task = registry.create_task(fail(), name="import:scene:42")
        try:
            await task
        except Boom:
            pass

    import asyncio

    asyncio.run(run())

    assert registry.failures == [{"name": "import:scene:42", "error_type": "Boom"}]
    assert emitted == [
        (
            "background_task_failed",
            {"level": "ERROR", "task_name": "import:scene:42", "error_type": "Boom"},
        )
    ]
