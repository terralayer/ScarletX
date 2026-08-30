from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ReleaseProfile


def _list(value: str) -> list[str]:
    try:
        raw = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item).strip().casefold() for item in raw if str(item).strip()]


def _scores(value: str) -> dict[str, int]:
    try:
        raw = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key, score in raw.items():
        try:
            result[str(key).strip().casefold()] = int(score)
        except (TypeError, ValueError):
            continue
    return result


def apply_release_profiles(
    db: Session,
    *,
    title: str,
    content_type: str,
    indexer: str | None = None,
) -> tuple[int, list[str]] | None:
    """Return (score adjustment, reasons), or None when a release is rejected."""
    profiles = db.scalars(
        select(ReleaseProfile).where(
            ReleaseProfile.enabled.is_(True),
            ReleaseProfile.content_type.in_((content_type, "all")),
        )
    ).all()
    lowered = title.casefold()
    adjustment = 0
    reasons: list[str] = []
    for profile in profiles:
        indexers = _list(profile.indexers_json)
        if indexers and (indexer or "").casefold() not in indexers:
            continue
        required = _list(profile.required_terms_json)
        if required and not all(term in lowered for term in required):
            return None
        ignored = _list(profile.ignored_terms_json)
        hit = next((term for term in ignored if term in lowered), None)
        if hit:
            return None
        for term, score in _scores(profile.preferred_scores_json).items():
            if term and term in lowered:
                adjustment += score
                reasons.append(f"{profile.name}: {term} {score:+d}")
    return adjustment, reasons
