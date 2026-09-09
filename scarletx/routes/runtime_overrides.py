from __future__ import annotations

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from ..dashboard_data import downloaded_scene_page, recent_studios
from ..db import get_session
from ..settings_store import set_setting


def dashboard_scenes_runtime(
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_session),
):
    return downloaded_scene_page(db, limit=limit)


def dashboard_studios_runtime(
    limit: int = Query(8, ge=1, le=50),
    db: Session = Depends(get_session),
):
    return {"items": recent_studios(db, limit=limit)}


def update_general_settings_runtime(request, db: Session = Depends(get_session)):
    """Preserve the legacy route shape while ignoring its obsolete app_name field."""
    level = str(getattr(request, "log_level", "INFO") or "INFO").strip().upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        level = "INFO"
    set_setting(db, "scarletx_log_level", level, commit=False)
    db.commit()
    return {"log_level": level}
