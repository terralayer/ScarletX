from __future__ import annotations

import base64
import json
import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from .models import MediaFile, Performer, Scene, Studio, scene_performer


def _encode_cursor(*parts: object) -> str:
    raw = json.dumps(parts, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> list[object]:
    if not value:
        return []
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception as exc:
        raise HTTPException(400, "Invalid pagination cursor") from exc
    if not isinstance(data, list):
        raise HTTPException(400, "Invalid pagination cursor")
    return data


def _fts_query(value: str | None) -> str | None:
    tokens = re.findall(r"[\w]+", (value or "").casefold(), flags=re.UNICODE)
    return " AND ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens[:12]
    ) or None


def _fts_available(db: Session, table: str) -> bool:
    bind = db.get_bind()
    if bind.dialect.name != "sqlite":
        return False
    try:
        return bool(
            db.scalar(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type='table' AND name=:name"
                ),
                {"name": table},
            )
        )
    except Exception:
        return False


def scene_summary_page(
    db: Session,
    *,
    limit: int,
    offset: int = 0,
    cursor: str | None = None,
    q: str | None = None,
) -> dict:
    filters = [Scene.content_type == "scene"]
    params: dict[str, object] = {}
    fts = _fts_query(q)
    if fts and _fts_available(db, "scene_search"):
        filters.append(
            text(
                "scenes.id IN "
                "(SELECT rowid FROM scene_search WHERE scene_search MATCH :fts_q)"
            )
        )
        params["fts_q"] = fts
    elif q:
        filters.append(Scene.title.ilike(f"%{q.strip()}%"))

    total = None
    if not cursor and offset == 0:
        total = db.scalar(select(func.count(Scene.id)).where(*filters).params(**params)) or 0

    cursor_parts = _decode_cursor(cursor)
    if cursor_parts:
        try:
            imported_at = datetime.fromisoformat(str(cursor_parts[0]))
            scene_id = int(cursor_parts[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise HTTPException(400, "Invalid scene pagination cursor") from exc
        filters.append(
            or_(
                Scene.imported_at < imported_at,
                and_(Scene.imported_at == imported_at, Scene.id < scene_id),
            )
        )

    has_file = (
        select(MediaFile.id)
        .where(MediaFile.scene_id == Scene.id)
        .exists()
        .label("has_file")
    )
    stmt = (
        select(
            Scene.id.label("id"),
            Scene.tpdb_id.label("tpdb_id"),
            Scene.title.label("title"),
            Scene.release_date.label("release_date"),
            func.coalesce(Scene.poster_url, Scene.image_url).label("image_url"),
            Scene.monitored.label("monitored"),
            Studio.name.label("studio"),
            Studio.tpdb_id.label("studio_id"),
            Scene.imported_at.label("imported_at"),
            has_file,
        )
        .outerjoin(Studio, Scene.studio_id == Studio.id)
        .where(*filters)
        .order_by(Scene.imported_at.desc(), Scene.id.desc())
    )
    if not cursor:
        stmt = stmt.offset(offset)

    fetched = db.execute(stmt.limit(limit + 1).params(**params)).mappings().all()
    has_more = len(fetched) > limit
    page_rows = fetched[:limit]
    scene_ids = [int(row["id"]) for row in page_rows]

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
            "has_file": bool(row["has_file"]),
        }
        for row in page_rows
    ]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last["imported_at"].isoformat(), last["id"])

    return {
        "total": int(total) if total is not None else None,
        "offset": offset if not cursor else None,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "items": items,
    }


def performer_summary_page(
    db: Session,
    *,
    limit: int,
    offset: int = 0,
    cursor: str | None = None,
    q: str | None = None,
) -> dict:
    filters = [Performer.is_library.is_(True)]
    params: dict[str, object] = {}
    fts = _fts_query(q)
    if fts and _fts_available(db, "performer_search"):
        filters.append(
            text(
                "performers.id IN "
                "(SELECT rowid FROM performer_search WHERE performer_search MATCH :fts_q)"
            )
        )
        params["fts_q"] = fts
    elif q:
        filters.append(Performer.name.ilike(f"%{q.strip()}%"))

    total = None
    if not cursor and offset == 0:
        total = db.scalar(
            select(func.count(Performer.id)).where(*filters).params(**params)
        ) or 0

    cursor_parts = _decode_cursor(cursor)
    if cursor_parts:
        try:
            last_name = str(cursor_parts[0])
            performer_id = int(cursor_parts[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise HTTPException(400, "Invalid performer pagination cursor") from exc
        filters.append(
            or_(
                Performer.name > last_name,
                and_(Performer.name == last_name, Performer.id > performer_id),
            )
        )

    stmt = (
        select(
            Performer.id.label("id"),
            Performer.tpdb_id.label("tpdb_id"),
            Performer.name.label("name"),
            Performer.image_url.label("image_url"),
            Performer.aliases.label("aliases"),
            Performer.monitored.label("monitored"),
        )
        .where(*filters)
        .order_by(Performer.name.asc(), Performer.id.asc())
    )
    if not cursor:
        stmt = stmt.offset(offset)
    fetched = db.execute(stmt.limit(limit + 1).params(**params)).mappings().all()
    has_more = len(fetched) > limit
    page_rows = fetched[:limit]
    items = [
        {
            "id": int(row["id"]),
            "tpdb_id": row["tpdb_id"],
            "name": row["name"],
            "image_url": row["image_url"],
            "aliases": row["aliases"],
            "monitored": bool(row["monitored"]),
        }
        for row in page_rows
    ]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last["name"], last["id"])
    return {
        "total": int(total) if total is not None else None,
        "offset": offset if not cursor else None,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "items": items,
    }


def studio_summary_page(
    db: Session,
    *,
    limit: int,
    offset: int = 0,
    cursor: str | None = None,
    q: str | None = None,
) -> dict:
    filters = [Studio.is_library.is_(True)]
    params: dict[str, object] = {}
    fts = _fts_query(q)
    if fts and _fts_available(db, "studio_search"):
        filters.append(
            text(
                "studios.id IN "
                "(SELECT rowid FROM studio_search WHERE studio_search MATCH :fts_q)"
            )
        )
        params["fts_q"] = fts
    elif q:
        filters.append(Studio.name.ilike(f"%{q.strip()}%"))

    total = None
    if not cursor and offset == 0:
        total = db.scalar(
            select(func.count(Studio.id)).where(*filters).params(**params)
        ) or 0

    cursor_parts = _decode_cursor(cursor)
    if cursor_parts:
        try:
            last_name = str(cursor_parts[0])
            studio_id = int(cursor_parts[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise HTTPException(400, "Invalid studio pagination cursor") from exc
        filters.append(
            or_(
                Studio.name > last_name,
                and_(Studio.name == last_name, Studio.id > studio_id),
            )
        )

    stmt = (
        select(
            Studio.id.label("id"),
            Studio.tpdb_id.label("tpdb_id"),
            Studio.name.label("name"),
            func.coalesce(Studio.poster_url, Studio.logo_url).label("image_url"),
            Studio.monitored.label("monitored"),
        )
        .where(*filters)
        .order_by(Studio.name.asc(), Studio.id.asc())
    )
    if not cursor:
        stmt = stmt.offset(offset)
    fetched = db.execute(stmt.limit(limit + 1).params(**params)).mappings().all()
    has_more = len(fetched) > limit
    page_rows = fetched[:limit]
    items = [
        {
            "id": int(row["id"]),
            "tpdb_id": row["tpdb_id"],
            "name": row["name"],
            "image_url": row["image_url"],
            "monitored": bool(row["monitored"]),
        }
        for row in page_rows
    ]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last["name"], last["id"])
    return {
        "total": int(total) if total is not None else None,
        "offset": offset if not cursor else None,
        "limit": limit,
        "has_more": has_more,
        "next_cursor": next_cursor,
        "items": items,
    }


def scene_summaries(db: Session, *, limit: int, cursor: str | None = None) -> list[dict]:
    return scene_summary_page(db, limit=limit, cursor=cursor)["items"]


def performer_summaries(
    db: Session, *, limit: int, cursor: str | None = None
) -> list[dict]:
    return performer_summary_page(db, limit=limit, cursor=cursor)["items"]


def studio_summaries(db: Session, *, limit: int, cursor: str | None = None) -> list[dict]:
    return studio_summary_page(db, limit=limit, cursor=cursor)["items"]
