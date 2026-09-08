from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import MediaFile, MediaProbe, Performer, Scene, Studio, scene_performer


def downloaded_scene_page(db: Session, *, limit: int = 8, offset: int = 0) -> dict:
    """Return only scenes that currently have at least one usable local media file."""
    usable_media = (
        select(MediaFile.id)
        .outerjoin(MediaProbe, MediaProbe.media_file_id == MediaFile.id)
        .where(
            MediaFile.scene_id == Scene.id,
            or_(MediaProbe.media_file_id.is_(None), MediaProbe.missing.is_(False)),
        )
        .order_by(MediaFile.id.asc())
        .limit(1)
        .correlate(Scene)
        .scalar_subquery()
    )
    filters = [Scene.content_type == "scene", usable_media.is_not(None)]
    total = db.scalar(select(func.count(Scene.id)).where(*filters)) or 0
    rows = db.execute(
        select(
            Scene.id.label("id"),
            Scene.tpdb_id.label("tpdb_id"),
            Scene.title.label("title"),
            Scene.release_date.label("release_date"),
            func.coalesce(func.nullif(Scene.poster_url, ""), Scene.image_url).label("image_url"),
            Scene.monitored.label("monitored"),
            Scene.imported_at.label("imported_at"),
            Studio.name.label("studio"),
            Studio.tpdb_id.label("studio_id"),
            usable_media.label("media_id"),
        )
        .outerjoin(Studio, Scene.studio_id == Studio.id)
        .where(*filters)
        .order_by(Scene.imported_at.desc(), Scene.id.desc())
        .offset(offset)
        .limit(limit)
    ).mappings().all()

    scene_ids = [int(row["id"]) for row in rows]
    performers_by_scene: dict[int, list[dict]] = {scene_id: [] for scene_id in scene_ids}
    if scene_ids:
        performer_rows = db.execute(
            select(
                scene_performer.c.scene_id,
                Performer.tpdb_id,
                Performer.name,
                Performer.image_url,
            )
            .join(Performer, scene_performer.c.performer_id == Performer.id)
            .where(scene_performer.c.scene_id.in_(scene_ids))
            .order_by(scene_performer.c.scene_id, Performer.name, Performer.id)
        ).all()
        for scene_id, tpdb_id, name, image_url in performer_rows:
            performers_by_scene[int(scene_id)].append(
                {"id": tpdb_id, "name": name, "image_url": image_url}
            )

    items = [
        {
            "id": int(row["id"]),
            "tpdb_id": row["tpdb_id"],
            "title": row["title"],
            "release_date": row["release_date"],
            "image_url": row["image_url"],
            "monitored": bool(row["monitored"]),
            "studio": row["studio"],
            "studio_id": row["studio_id"],
            "performers": performers_by_scene[int(row["id"])],
            "has_file": True,
            "media_id": row["media_id"],
        }
        for row in rows
    ]
    return {
        "total": int(total),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(items) < int(total),
        "next_cursor": None,
        "items": items,
    }
