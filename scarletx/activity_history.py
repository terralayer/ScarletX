from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import History


router = APIRouter()
EVENT_TYPE_COUNT_LIMIT = 100


def _history_item(row: History) -> dict:
    return {
        "id": row.id,
        "event_type": row.event_type,
        "scene_id": row.scene_id,
        "message": row.message,
        "created_at": row.created_at,
        "content_type": "scene" if row.scene_id else None,
    }


@router.get("/api/history/page")
def activity_history_page(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    event_type: str | None = Query(None, max_length=50),
    db: Session = Depends(get_session),
):
    selected_type = (event_type or "").strip() or None

    count_stmt = select(func.count(History.id))
    page_stmt = select(History)
    if selected_type:
        count_stmt = count_stmt.where(History.event_type == selected_type)
        page_stmt = page_stmt.where(History.event_type == selected_type)

    total = int(db.scalar(count_stmt) or 0)
    rows = db.scalars(
        page_stmt
        .order_by(History.created_at.desc(), History.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    count_rows = db.execute(
        select(History.event_type, func.count(History.id))
        .group_by(History.event_type)
        .order_by(History.event_type)
        .limit(EVENT_TYPE_COUNT_LIMIT)
    ).all()
    event_counts = {str(kind): int(count) for kind, count in count_rows if kind}

    return {
        "items": [_history_item(row) for row in rows],
        "page": page,
        "limit": limit,
        "total": total,
        "event_counts": event_counts,
    }
