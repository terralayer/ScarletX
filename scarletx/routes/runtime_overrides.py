from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..dashboard_data import downloaded_scene_page
from ..db import get_session
from ..list_queries import scene_summary_page
from ..settings_store import set_setting

router = APIRouter()


class GeneralSettingsRuntimeWrite(BaseModel):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


@router.get("/api/library/scenes/page")
def library_scene_page_runtime(
    limit: int = Query(100, ge=1, le=250),
    offset: int = Query(0, ge=0),
    cursor: str | None = None,
    q: str | None = None,
    downloaded_only: bool = False,
    db: Session = Depends(get_session),
):
    if downloaded_only:
        # Dashboard uses a tiny first page; cursor/search stay on the full library API.
        return downloaded_scene_page(db, limit=limit, offset=offset)
    return scene_summary_page(db, limit=limit, offset=offset, q=q, cursor=cursor)


@router.patch("/api/settings/general")
def update_general_settings_runtime(
    request: GeneralSettingsRuntimeWrite,
    db: Session = Depends(get_session),
):
    set_setting(db, "scarletx_log_level", request.log_level, commit=False)
    db.commit()
    return {"log_level": request.log_level}
