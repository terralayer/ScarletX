from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import MediaFile, MediaProbe, Scene, UnmatchedMediaFile

ISSUE_LIMIT = 50

router = APIRouter()


def _count_missing(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(MediaProbe.media_file_id)).where(MediaProbe.missing.is_(True))
        )
        or 0
    )


def _count_unmatched(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(UnmatchedMediaFile.id)).where(
                UnmatchedMediaFile.missing.is_(False)
            )
        )
        or 0
    )


def _count_unprobed(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(MediaFile.id))
            .outerjoin(MediaProbe, MediaProbe.media_file_id == MediaFile.id)
            .where(MediaProbe.media_file_id.is_(None))
        )
        or 0
    )


def _missing_issues(db: Session, limit: int) -> list[dict[str, object]]:
    if limit <= 0:
        return []
    rows = db.execute(
        select(MediaFile.id, Scene.id, Scene.title, MediaFile.size_bytes)
        .join(MediaProbe, MediaProbe.media_file_id == MediaFile.id)
        .join(Scene, Scene.id == MediaFile.scene_id)
        .where(MediaProbe.missing.is_(True))
        .order_by(MediaProbe.scanned_at.desc(), MediaFile.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "kind": "missing",
            "media_file_id": media_file_id,
            "scene_id": scene_id,
            "title": title,
            "detail": "Tracked media file is missing",
            "size_bytes": size_bytes,
        }
        for media_file_id, scene_id, title, size_bytes in rows
    ]


def _unmatched_issues(db: Session, limit: int) -> list[dict[str, object]]:
    if limit <= 0:
        return []
    rows = db.execute(
        select(
            UnmatchedMediaFile.id,
            UnmatchedMediaFile.display_name,
            UnmatchedMediaFile.size_bytes,
        )
        .where(UnmatchedMediaFile.missing.is_(False))
        .order_by(UnmatchedMediaFile.last_seen_at.desc(), UnmatchedMediaFile.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "kind": "unmatched",
            "unmatched_id": unmatched_id,
            "title": display_name,
            "detail": "File needs a scene match",
            "size_bytes": size_bytes,
        }
        for unmatched_id, display_name, size_bytes in rows
    ]


def _unprobed_issues(db: Session, limit: int) -> list[dict[str, object]]:
    if limit <= 0:
        return []
    rows = db.execute(
        select(MediaFile.id, Scene.id, Scene.title, MediaFile.size_bytes)
        .outerjoin(MediaProbe, MediaProbe.media_file_id == MediaFile.id)
        .join(Scene, Scene.id == MediaFile.scene_id)
        .where(MediaProbe.media_file_id.is_(None))
        .order_by(MediaFile.imported_at.desc(), MediaFile.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "kind": "unprobed",
            "media_file_id": media_file_id,
            "scene_id": scene_id,
            "title": title,
            "detail": "Technical media metadata has not been probed",
            "size_bytes": size_bytes,
        }
        for media_file_id, scene_id, title, size_bytes in rows
    ]


@router.get("/api/media-library/health")
def library_health(db: Session = Depends(get_session)) -> dict[str, object]:
    missing = _count_missing(db)
    unmatched = _count_unmatched(db)
    unprobed = _count_unprobed(db)

    issues = _missing_issues(db, ISSUE_LIMIT)
    remaining = ISSUE_LIMIT - len(issues)
    issues.extend(_unmatched_issues(db, remaining))
    remaining = ISSUE_LIMIT - len(issues)
    issues.extend(_unprobed_issues(db, remaining))

    total = missing + unmatched + unprobed
    return {
        "healthy": total == 0,
        "counts": {
            "missing": missing,
            "unmatched": unmatched,
            "unprobed": unprobed,
            "total": total,
        },
        "issues": issues,
    }
