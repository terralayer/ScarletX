from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO


MAX_FIELDS = 24
MAX_COLLECTION_ITEMS = 16
MAX_DEPTH = 4
MAX_STRING_LENGTH = 256
REDACTED = "[REDACTED]"
_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "passwd",
    "password",
    "secret",
    "token",
)
_CONTROL_WHITESPACE = re.compile(r"[\x00-\x1f\x7f]+")
_SPACES = re.compile(r"\s+")


def _secret_key(key: object) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _bounded_text(value: object, *, limit: int = MAX_STRING_LENGTH) -> str:
    text = _CONTROL_WHITESPACE.sub(" ", str(value))
    text = _SPACES.sub(" ", text).strip()
    return text[:limit]


def _sanitize_value(key: object, value: Any, *, depth: int = 0) -> Any:
    if _secret_key(key):
        return REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _bounded_text(value)
    if depth >= MAX_DEPTH:
        return _bounded_text(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (child_key, child_value) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                break
            safe_key = _bounded_text(child_key, limit=64) or "field"
            result[safe_key] = _sanitize_value(child_key, child_value, depth=depth + 1)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _sanitize_value(index, child, depth=depth + 1)
            for index, child in enumerate(value[:MAX_COLLECTION_ITEMS])
        ]
    return _bounded_text(value)


def build_log_record(event: str, *, level: str = "INFO", **fields: Any) -> dict[str, Any]:
    """Build one bounded, secret-safe structured runtime log record."""
    payload: dict[str, Any] = {
        "event": _bounded_text(event, limit=128),
        "level": _bounded_text(level, limit=16).upper() or "INFO",
    }
    for key, value in fields.items():
        if len(payload) >= MAX_FIELDS:
            break
        safe_key = _bounded_text(key, limit=64) or "field"
        payload[safe_key] = _sanitize_value(key, value)
    return payload


def emit_structured_log(
    event: str,
    *,
    level: str = "INFO",
    stream: TextIO | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Write one compact JSON line and return the sanitized payload."""
    payload = build_log_record(event, level=level, **fields)
    destination = stream if stream is not None else sys.stderr
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True), file=destination, flush=True)
    return payload
