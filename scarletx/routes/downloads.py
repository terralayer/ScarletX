from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.routing import APIRoute
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import NativeUsenetJob, TrackedDownload

"""Download queue, activity, history, and job routes."""

PREFIXES = ('/api/activity', '/api/downloads', '/api/history', '/api/jobs')
ACTIVE_STATES = ("queued", "downloading", "paused", "postprocessing", "import_pending")
router = APIRouter()


def _active_download_predicate():
    native_active = select(NativeUsenetJob.id).where(NativeUsenetJob.status.in_(ACTIVE_STATES))
    return or_(
        TrackedDownload.status.in_(ACTIVE_STATES),
        TrackedDownload.client_status.in_(ACTIVE_STATES),
        TrackedDownload.nzo_id.in_(native_active),
    )


def _active_download_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count(TrackedDownload.id)).where(_active_download_predicate())
        )
        or 0
    )


def activity_count(db: Session = Depends(get_session)) -> dict[str, int]:
    """Return the real active-download count without the live snapshot's row cap."""
    return {"active": _active_download_count(db)}


def activity_page(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_session),
) -> dict:
    """Return one server-side page of active downloads plus the true total."""
    items = db.scalars(
        select(TrackedDownload)
        .where(_active_download_predicate())
        .order_by(TrackedDownload.created_at.asc())
        .offset((page - 1) * limit).limit(limit)
    ).all()
    # Imported lazily because application.py imports this route boundary module
    # only after its serializer has been defined.
    from .application import _tracked_download_rows

    return {
        "items": _tracked_download_rows(db, items),
        "total": _active_download_count(db),
        "page": page,
        "limit": limit,
    }


def adopt_routes(app) -> None:
    if router.routes:
        return

    existing_paths = {
        route.path for route in app.router.routes
        if isinstance(route, APIRoute)
    }
    if "/api/activity/count" not in existing_paths:
        app.add_api_route("/api/activity/count", activity_count, methods=["GET"])
    if "/api/activity/page" not in existing_paths:
        app.add_api_route("/api/activity/page", activity_page, methods=["GET"])

    selected = [
        route for route in app.router.routes
        if isinstance(route, APIRoute)
        and any(route.path.startswith(prefix) for prefix in PREFIXES)
    ]
    if not selected:
        return
    # Keep the application's registered route objects untouched. The focused
    # router is an ownership/introspection view over those exact objects, so paths,
    # methods, dependencies, names, middleware behavior, and OpenAPI stay identical.
    router.routes.extend(selected)
