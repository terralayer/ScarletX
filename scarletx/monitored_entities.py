from __future__ import annotations

from sqlalchemy import select

from .metadata import metadata_client
from .models import Performer, Scene, Studio
from .services import upsert_scene

ENTITY_PAGE_SIZE = 48
MAX_ENTITY_PAGES = 50


def client(settings):
    return metadata_client(settings)


async def _performer_scenes(tpdb, identifier: str):
    page = 1
    while page <= MAX_ENTITY_PAGES:
        response = await tpdb.get_performer_scenes(
            identifier,
            page=page,
            per_page=ENTITY_PAGE_SIZE,
        )
        for scene in response.items:
            yield scene
        if not response.items or page * response.per_page >= response.total:
            break
        page += 1


async def _studio_scenes(tpdb, identifier: str):
    studio = await tpdb.get_studio(identifier)
    if studio.search_id is None:
        raise RuntimeError(f"Studio {identifier} has no searchable TPDB site ID")
    page = 1
    while page <= MAX_ENTITY_PAGES:
        response = await tpdb.search_scenes(
            page=page,
            per_page=ENTITY_PAGE_SIZE,
            site_id=str(studio.search_id),
        )
        for scene in response.items:
            yield scene
        if not response.items or page * response.per_page >= response.total:
            break
        page += 1


async def monitored_entity_discovery_cycle(session_factory, settings) -> dict:
    """Refresh monitored performers/studios from TPDB and persist their scenes.

    The entity monitor flags are the durable source of truth.  Scene discovery is
    idempotent by TPDB scene ID, and one failing entity never prevents the other
    monitored entities from being refreshed.
    """
    with session_factory() as db:
        performers = [
            (row.tpdb_id, row.name)
            for row in db.scalars(
                select(Performer).where(Performer.monitored.is_(True))
            ).all()
        ]
        studios = [
            (row.tpdb_id, row.name)
            for row in db.scalars(
                select(Studio).where(Studio.monitored.is_(True))
            ).all()
        ]

    discovered = {}
    errors: list[dict[str, str]] = []
    async with client(settings) as tpdb:
        for identifier, name in performers:
            try:
                async for scene in _performer_scenes(tpdb, identifier):
                    discovered[scene.id] = scene
            except Exception as exc:
                errors.append(
                    {
                        "type": "performer",
                        "id": identifier,
                        "name": name,
                        "error": str(exc),
                    }
                )

        for identifier, name in studios:
            try:
                async for scene in _studio_scenes(tpdb, identifier):
                    discovered[scene.id] = scene
            except Exception as exc:
                errors.append(
                    {
                        "type": "studio",
                        "id": identifier,
                        "name": name,
                        "error": str(exc),
                    }
                )

    with session_factory() as db:
        existing_ids = set(
            db.scalars(
                select(Scene.tpdb_id).where(Scene.tpdb_id.in_(tuple(discovered)))
            ).all()
        ) if discovered else set()

    created = 0
    refreshed = 0
    for remote in discovered.values():
        with session_factory() as db:
            scene = upsert_scene(db, remote, monitored=True, content_type="scene")
            if not scene.monitored:
                scene.monitored = True
                db.commit()
        if remote.id in existing_ids:
            refreshed += 1
        else:
            created += 1

    return {
        "entities_checked": len(performers) + len(studios),
        "performers_checked": len(performers),
        "studios_checked": len(studios),
        "unique_scenes": len(discovered),
        "created": created,
        "refreshed": refreshed,
        "errors": errors,
    }
