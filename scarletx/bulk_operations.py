from __future__ import annotations

from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .automation import search_and_grab_scene
from .db import SessionLocal, get_session
from .models import Scene
from .settings_store import load_database_settings


class BulkWantedRequest(BaseModel):
    action: Literal["search", "unmonitor"]
    scene_ids: list[int] = Field(min_length=1, max_length=25)


def _dedupe_scene_ids(scene_ids: list[int]) -> list[int]:
    return list(dict.fromkeys(int(scene_id) for scene_id in scene_ids))


async def bulk_wanted(
    request: BulkWantedRequest,
    db: Session = Depends(get_session),
) -> dict:
    scene_ids = _dedupe_scene_ids(request.scene_ids)
    rows = db.scalars(
        select(Scene).where(
            Scene.id.in_(scene_ids),
            Scene.content_type == "scene",
        )
    ).all()
    scenes = {int(scene.id): scene for scene in rows}
    missing = [scene_id for scene_id in scene_ids if scene_id not in scenes]
    if missing:
        raise HTTPException(
            404,
            detail={"message": "Unknown scene ids", "scene_ids": missing},
        )

    if request.action == "unmonitor":
        for scene_id in scene_ids:
            scenes[scene_id].monitored = False
        db.commit()
        return {
            "action": request.action,
            "requested": len(scene_ids),
            "processed": len(scene_ids),
            "results": [
                {"scene_id": scene_id, "status": "unmonitored"}
                for scene_id in scene_ids
            ],
        }

    settings = load_database_settings(db)
    results = []
    for scene_id in scene_ids:
        result = await search_and_grab_scene(SessionLocal, scene_id, settings)
        results.append(result.as_dict())
    return {
        "action": request.action,
        "requested": len(scene_ids),
        "processed": len(results),
        "results": results,
    }
