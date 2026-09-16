from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DuplicateEvidence:
    tpdb_id: str | None = None
    source_guid: str | None = None
    content_hash: str | None = None
    quick_fingerprint: str | None = None
    size_bytes: int | None = None
    duration_seconds: float | None = None


@dataclass(frozen=True)
class DuplicateDecision:
    classification: str
    automatic: bool
    reasons: tuple[str, ...] = ()


def _same_nonblank(first: str | None, second: str | None) -> bool:
    return bool(first and second and first.strip() and first.strip() == second.strip())


def _size_duration_similar(first: DuplicateEvidence, second: DuplicateEvidence) -> bool:
    if (
        first.size_bytes is None
        or second.size_bytes is None
        or first.duration_seconds is None
        or second.duration_seconds is None
    ):
        return False
    if first.size_bytes <= 0 or second.size_bytes <= 0:
        return False
    if first.duration_seconds <= 0 or second.duration_seconds <= 0:
        return False

    larger_size = max(first.size_bytes, second.size_bytes)
    size_delta = abs(first.size_bytes - second.size_bytes)
    size_close = size_delta <= max(20 * 1024**2, int(larger_size * 0.01))

    longer_duration = max(first.duration_seconds, second.duration_seconds)
    duration_delta = abs(first.duration_seconds - second.duration_seconds)
    duration_close = duration_delta <= max(2.0, longer_duration * 0.005)
    return size_close and duration_close


def classify_duplicate(first: DuplicateEvidence, second: DuplicateEvidence) -> DuplicateDecision:
    """Classify evidence without auto-deleting media on probabilistic similarity."""

    if first.tpdb_id and second.tpdb_id and first.tpdb_id != second.tpdb_id:
        return DuplicateDecision("distinct", False, ("tpdb_conflict",))

    if _same_nonblank(first.source_guid, second.source_guid):
        return DuplicateDecision("duplicate", True, ("source_guid",))

    if _same_nonblank(first.content_hash, second.content_hash):
        return DuplicateDecision("duplicate", True, ("content_hash",))

    reasons: list[str] = []
    if _same_nonblank(first.quick_fingerprint, second.quick_fingerprint):
        reasons.append("quick_fingerprint")

    same_scene = _same_nonblank(first.tpdb_id, second.tpdb_id)
    if same_scene and _size_duration_similar(first, second):
        reasons.append("size_duration")

    if reasons:
        return DuplicateDecision("review", False, tuple(reasons))
    return DuplicateDecision("distinct", False)
