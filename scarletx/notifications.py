from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .models import Webhook


def _json(value: str, fallback):
    try:
        data = json.loads(value or "")
        return data
    except (TypeError, json.JSONDecodeError):
        return fallback


async def emit_webhooks(
    session_factory: sessionmaker,
    event: str,
    payload: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, int]:
    with session_factory() as db:
        hooks = db.scalars(select(Webhook).where(Webhook.enabled.is_(True))).all()
        configs = []
        for hook in hooks:
            events = [str(x).casefold() for x in _json(hook.events_json, [])]
            if events and event.casefold() not in events and "all" not in events:
                continue
            configs.append({
                "name": hook.name,
                "url": hook.url,
                "headers": _json(hook.headers_json, {}),
                "secret": hook.secret or "",
            })

    body = {"event": event, **payload}
    raw = json.dumps(body, separators=(",", ":"), default=str).encode()
    sent = failed = 0
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        for hook in configs:
            headers = {str(k): str(v) for k, v in hook["headers"].items()}
            headers.setdefault("Content-Type", "application/json")
            headers["X-ScarletX-Event"] = event
            if hook["secret"]:
                digest = hmac.new(hook["secret"].encode(), raw, hashlib.sha256).hexdigest()
                headers["X-ScarletX-Signature"] = f"sha256={digest}"
            try:
                response = await client.post(hook["url"], content=raw, headers=headers)
                response.raise_for_status()
                sent += 1
            except (httpx.HTTPError, httpx.TimeoutException):
                failed += 1
    return {"sent": sent, "failed": failed}
