from __future__ import annotations

import errno
import re
from dataclasses import dataclass


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|authorization|bearer|token|secret)\s*[:=]\s*([^\s;,]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_MAX_DETAIL = 512


@dataclass(frozen=True)
class FailureClassification:
    code: str
    retryable: bool
    quarantine: bool
    detail: str


def _safe_detail(exc: BaseException) -> str:
    text = f"{exc.__class__.__name__}: {exc}".strip()
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _BEARER_VALUE.sub("Bearer [REDACTED]", text)
    # Keep operational messages useful while preventing giant provider/tool output
    # from being copied into queue rows and history events.
    return text[:_MAX_DETAIL]


def _text(exc: BaseException) -> str:
    return str(exc).casefold()


def classify_failure(exc: BaseException) -> FailureClassification:
    """Map low-level failures into stable queue semantics.

    The classifier deliberately does not persist credentials or raw transport
    payloads. Callers can use ``retryable`` for bounded backoff and ``quarantine``
    to keep terminal/bad-payload work out of the runnable queue.
    """

    detail = _safe_detail(exc)
    message = _text(exc)

    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in {
        errno.EACCES,
        errno.EPERM,
    }:
        return FailureClassification("permission_denied", False, True, detail)

    if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
        return FailureClassification("disk_full", False, True, detail)

    if isinstance(exc, (TimeoutError, ConnectionError)) or any(
        marker in message
        for marker in ("timed out", "timeout", "connection reset", "connection closed")
    ):
        return FailureClassification("provider_timeout", True, False, detail)

    if isinstance(exc, FileNotFoundError) and any(
        marker in message for marker in ("article", "segment", "unavailable", "missing")
    ):
        return FailureClassification("missing_article", True, False, detail)

    if any(
        marker in message
        for marker in (
            "authentication failed",
            "authorization failed",
            "invalid credentials",
            "401",
            "403",
        )
    ):
        return FailureClassification("authentication_failed", False, True, detail)

    if any(
        marker in message
        for marker in (
            "crc mismatch",
            "corrupt",
            "invalid archive",
            "unexpected end of archive",
            "truncated",
        )
    ):
        return FailureClassification("corrupt_payload", False, True, detail)

    if any(marker in message for marker in ("no playable", "unsupported media", "no video stream")):
        return FailureClassification("unsupported_media", False, True, detail)

    if any(marker in message for marker in ("ambiguous match", "metadata mismatch", "tpdb mismatch")):
        return FailureClassification("metadata_mismatch", False, True, detail)

    if any(marker in message for marker in ("already exists", "duplicate release", "duplicate download")):
        return FailureClassification("duplicate", False, True, detail)

    return FailureClassification("unknown", False, True, detail)
