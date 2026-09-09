from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import MediaFile, MediaProbe, Performer, Scene, Studio, scene_performer


def _usable_media_id():
    return (
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


def _release_order():
    return (
        Scene.release_date.is_(None).asc(),
        Scene.release_date.desc(),
        Scene.id.desc(),
    )


def downloaded_scene_page(db: Session, *, limit: int = 8, offset: int = 0) -> dict:
    """Return downloaded scenes ordered by release date, newest first."""
    usable_media = _usable_media_id()
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
            Studio.name.label("studio"),
            Studio.tpdb_id.label("studio_id"),
            usable_media.label("media_id"),
        )
        .outerjoin(Studio, Scene.studio_id == Studio.id)
        .where(*filters)
        .order_by(*_release_order())
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


def recent_studios(db: Session, *, limit: int = 8) -> list[dict]:
    """Studios ranked by the newest release date among their downloaded scenes."""
    usable_media = _usable_media_id()
    downloaded = [
        Scene.content_type == "scene",
        Scene.studio_id.is_not(None),
        usable_media.is_not(None),
    ]
    grouped = db.execute(
        select(
            Studio.id.label("id"),
            Studio.tpdb_id.label("tpdb_id"),
            Studio.name.label("name"),
            func.count(Scene.id).label("release_count"),
            func.max(Scene.release_date).label("latest_release_date"),
        )
        .join(Scene, Scene.studio_id == Studio.id)
        .where(*downloaded)
        .group_by(Studio.id, Studio.tpdb_id, Studio.name)
        .order_by(
            func.max(Scene.release_date).is_(None).asc(),
            func.max(Scene.release_date).desc(),
            Studio.id.desc(),
        )
        .limit(limit)
    ).mappings().all()
    if not grouped:
        return []

    studio_ids = [int(row["id"]) for row in grouped]
    latest_rows = db.execute(
        select(
            Scene.studio_id,
            Scene.tpdb_id,
            Scene.title,
            Scene.release_date,
            Scene.id,
        )
        .where(
            Scene.studio_id.in_(studio_ids),
            Scene.content_type == "scene",
            _usable_media_id().is_not(None),
        )
        .order_by(
            Scene.studio_id.asc(),
            Scene.release_date.is_(None).asc(),
            Scene.release_date.desc(),
            Scene.id.desc(),
        )
    ).all()
    latest_by_studio: dict[int, tuple] = {}
    for row in latest_rows:
        latest_by_studio.setdefault(int(row.studio_id), row)

    result = []
    for row in grouped:
        latest = latest_by_studio.get(int(row["id"]))
        result.append(
            {
                "id": int(row["id"]),
                "tpdb_id": row["tpdb_id"],
                "name": row["name"],
                "release_count": int(row["release_count"] or 0),
                "latest_release_date": latest.release_date if latest else row["latest_release_date"],
                "latest_scene_id": latest.tpdb_id if latest else None,
                "latest_title": latest.title if latest else None,
            }
        )
    return result
