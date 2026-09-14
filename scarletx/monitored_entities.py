from __future__ import annotations

import asyncio
import json
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from .metadata import metadata_client
from .models import AppSetting, Performer, Scene, Studio, scene_performer
from .services import upsert_scene

ENTITY_PAGE_SIZE = 48
MAX_ENTITY_PAGES = 1000
ENTITY_SCAN_CONCURRENCY = 3


def client(settings):
    return metadata_client(settings)


def _cursor_key(kind: str, local_id: int) -> str:
    return f"monitored_scan:{kind}:{local_id}"


def _studio_deep_scan_key(local_id: int) -> str:
    return f"monitored_scan:studio_deep:{local_id}"


def _performer_deep_scan_key(local_id: int) -> str:
    return f"monitored_scan:performer_deep:{local_id}"


def _load_head_cursor(db, kind: str, local_id: int) -> tuple[str, ...]:
    row = db.get(AppSetting, _cursor_key(kind, local_id))
    if row is None:
        return ()
    try:
        payload = json.loads(row.value or "{}")
        values = payload.get("head_ids") or []
        return tuple(str(value) for value in values if value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()


def _save_head_cursor(db, kind: str, local_id: int, head_ids: tuple[str, ...]) -> None:
    key = _cursor_key(kind, local_id)
    value = json.dumps({"head_ids": list(head_ids)}, separators=(",", ":"))
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, is_secret=False))
    else:
        row.value = value


def _studio_deep_scan_due(db, local_id: int, today: date | None = None) -> bool:
    today = today or date.today()
    row = db.get(AppSetting, _studio_deep_scan_key(local_id))
    return row is None or row.value != today.isoformat()


def _save_studio_deep_scan(db, local_id: int, today: date | None = None) -> None:
    today = today or date.today()
    key = _studio_deep_scan_key(local_id)
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=today.isoformat(), is_secret=False))
    else:
        row.value = today.isoformat()


def _performer_deep_scan_due(db, local_id: int, today: date | None = None) -> bool:
    today = today or date.today()
    row = db.get(AppSetting, _performer_deep_scan_key(local_id))
    return row is None or row.value != today.isoformat()


def _save_performer_deep_scan(db, local_id: int, today: date | None = None) -> None:
    today = today or date.today()
    key = _performer_deep_scan_key(local_id)
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=today.isoformat(), is_secret=False))
    else:
        row.value = today.isoformat()


def _scene_head_fingerprint(scene) -> str:
    """Fingerprint first-page fields that can change Calendar membership/display.

    Older cursors stored only scene IDs. Those legacy values intentionally compare
    different once after this upgrade, causing one metadata refresh before the new
    fingerprints become the durable fast-path cursor.
    """
    release_date = getattr(scene, "release_date", None)
    if hasattr(release_date, "isoformat"):
        release_token = release_date.isoformat()
    else:
        release_token = str(release_date or "")
    studio = getattr(scene, "studio", None)
    studio_id = str(getattr(studio, "id", "") or "")
    performer_ids = sorted(
        str(getattr(performer, "id", "") or "")
        for performer in (getattr(scene, "performers", None) or [])
        if getattr(performer, "id", None)
    )
    return json.dumps(
        [str(scene.id), str(getattr(scene, "title", "") or ""), release_token, studio_id, performer_ids],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _entity_metadata_id(entity) -> str:
    if entity is None:
        return ""
    return str(getattr(entity, "tpdb_id", None) or getattr(entity, "id", "") or "")


def _scene_metadata_fingerprint(scene) -> str:
    """Compare only discovery-critical metadata before rewriting an existing scene.

    Daily deep discovery exists to discover new monitored releases and keep Calendar
    ownership/date metadata current. Rewriting thousands of already-identical scenes
    creates long SQLite writer transactions without changing acquisition behavior.
    """
    release_date = getattr(scene, "release_date", None)
    if hasattr(release_date, "isoformat"):
        release_token = release_date.isoformat()
    else:
        release_token = str(release_date or "")
    studio_id = _entity_metadata_id(getattr(scene, "studio", None))
    performer_ids = sorted(
        _entity_metadata_id(performer)
        for performer in (getattr(scene, "performers", None) or [])
        if _entity_metadata_id(performer)
    )
    return json.dumps(
        [str(getattr(scene, "title", "") or ""), release_token, studio_id, performer_ids],
        separators=(",", ":"),
        ensure_ascii=False,
    )


async def _performer_scan(
    tpdb,
    identifier: str,
    previous_head: tuple[str, ...],
    *,
    force_deep: bool = False,
):
    first = await tpdb.get_performer_scenes(identifier, page=1, per_page=ENTITY_PAGE_SIZE)
    head = tuple(_scene_head_fingerprint(scene) for scene in first.items)
    if previous_head and head == previous_head and not force_deep:
        return [], head, True

    scenes = list(first.items)
    page = 2
    while page <= MAX_ENTITY_PAGES and (page - 1) * first.per_page < first.total:
        response = await tpdb.get_performer_scenes(identifier, page=page, per_page=ENTITY_PAGE_SIZE)
        scenes.extend(response.items)
        if page * response.per_page >= response.total:
            break
        page += 1
    return scenes, head, False


async def _studio_scan(
    tpdb,
    identifier: str,
    previous_head: tuple[str, ...],
    *,
    force_deep: bool = False,
):
    studio = await tpdb.get_studio(identifier)
    search_id = studio.search_id
    if search_id is None and identifier.isdigit():
        search_id = int(identifier)
    if search_id is None:
        raise RuntimeError(f"Studio {identifier} has no searchable TPDB site ID")
    first = await tpdb.search_scenes(page=1, per_page=ENTITY_PAGE_SIZE, site_id=str(search_id))
    head = tuple(_scene_head_fingerprint(scene) for scene in first.items)
    if previous_head and head == previous_head and not force_deep:
        return [], head, True

    scenes = list(first.items)
    page = 2
    while page <= MAX_ENTITY_PAGES and (page - 1) * first.per_page < first.total:
        response = await tpdb.search_scenes(
            page=page,
            per_page=ENTITY_PAGE_SIZE,
            site_id=str(search_id),
        )
        scenes.extend(response.items)
        if page * response.per_page >= response.total:
            break
        page += 1
    return scenes, head, False


def _persist_discovered_scenes(
    session_factory,
    discovered: dict,
    cursor_updates: list[tuple[str, int, tuple[str, ...]]],
    studio_deep_scan_updates: list[int],
    performer_deep_scan_updates: list[int],
) -> tuple[int, int, set[int], list[dict[str, str]]]:
    """Persist only new/changed discovery results outside the web event loop.

    A daily deep scan can return many thousands of already-known scenes. Compare a
    compact Calendar/acquisition fingerprint first so identical historical rows do not
    participate in the SQLite write transaction at all.
    """
    existing_fingerprints: dict[str, str] = {}
    if discovered:
        with session_factory() as db:
            rows = db.scalars(
                select(Scene)
                .where(Scene.tpdb_id.in_(tuple(discovered)))
                .options(selectinload(Scene.performers), selectinload(Scene.studio))
            ).all()
            existing_fingerprints = {
                row.tpdb_id: _scene_metadata_fingerprint(row)
                for row in rows
                if row.tpdb_id
            }

    pending = [
        remote
        for remote in discovered.values()
        if remote.id not in existing_fingerprints
        or existing_fingerprints[remote.id] != _scene_metadata_fingerprint(remote)
    ]

    created = 0
    refreshed = 0
    persisted_scene_ids: set[int] = set()
    errors: list[dict[str, str]] = []
    scene_write_failed = False

    with session_factory() as db:
        for remote in pending:
            try:
                # SAVEPOINT isolates one malformed remote scene while retaining a
                # single outer commit for the much smaller changed-scene batch.
                with db.begin_nested():
                    scene = upsert_scene(db, remote, monitored=True, content_type="scene", commit=False)
                    if not scene.monitored:
                        scene.monitored = True
                    persisted_scene_ids.add(scene.id)
                if remote.id in existing_fingerprints:
                    refreshed += 1
                else:
                    created += 1
            except Exception as exc:
                scene_write_failed = True
                errors.append({"type": "scene", "id": remote.id, "name": remote.title, "error": str(exc)})

        # Advance remote cursors/deep-scan markers only when every changed/new scene
        # was durably handled. A failed upsert retries the deeper scan next hour.
        if cursor_updates and not scene_write_failed:
            for kind, local_id, head in cursor_updates:
                _save_head_cursor(db, kind, local_id, head)
            for local_id in studio_deep_scan_updates:
                _save_studio_deep_scan(db, local_id)
            for local_id in performer_deep_scan_updates:
                _save_performer_deep_scan(db, local_id)
        db.commit()

    return created, refreshed, persisted_scene_ids, errors


async def monitored_entity_discovery_cycle(session_factory, settings) -> dict:
    """Incrementally refresh monitored performers/studios from TPDB.

    Monitored performer/studio relationships are the durable source of truth for
    acquisition. Performer and studio discovery each perform one deep scan per local
    calendar day so future releases cannot remain hidden behind an unchanged first
    page. Only new/changed TPDB scenes are written, and synchronous persistence runs
    off the request event loop.
    """
    with session_factory() as db:
        performers = [
            (
                row.id,
                row.tpdb_id,
                row.name,
                _load_head_cursor(db, "performer", row.id),
                _performer_deep_scan_due(db, row.id),
            )
            for row in db.scalars(select(Performer).where(Performer.monitored.is_(True))).all()
        ]
        studios = [
            (
                row.id,
                row.tpdb_id,
                row.name,
                _load_head_cursor(db, "studio", row.id),
                _studio_deep_scan_due(db, row.id),
            )
            for row in db.scalars(select(Studio).where(Studio.monitored.is_(True))).all()
        ]
        performer_ids = [row[0] for row in performers]
        studio_ids = [row[0] for row in studios]
        candidate_scene_ids = set(
            db.scalars(
                select(scene_performer.c.scene_id).where(scene_performer.c.performer_id.in_(performer_ids))
            ).all()
        ) if performer_ids else set()
        if studio_ids:
            candidate_scene_ids.update(
                db.scalars(select(Scene.id).where(Scene.studio_id.in_(studio_ids))).all()
            )
        if candidate_scene_ids:
            db.execute(
                update(Scene)
                .where(Scene.id.in_(candidate_scene_ids), Scene.monitored.is_(False))
                .values(monitored=True)
            )
            db.commit()

    discovered = {}
    errors: list[dict[str, str]] = []
    cursor_updates: list[tuple[str, int, tuple[str, ...]]] = []
    studio_deep_scan_updates: list[int] = []
    performer_deep_scan_updates: list[int] = []
    unchanged_entities = 0
    semaphore = asyncio.Semaphore(ENTITY_SCAN_CONCURRENCY)

    async with client(settings) as tpdb:
        async def scan_performer(local_id, identifier, name, previous_head, deep_scan_due):
            async with semaphore:
                try:
                    scenes, head, unchanged = await _performer_scan(
                        tpdb,
                        identifier,
                        previous_head,
                        force_deep=deep_scan_due,
                    )
                    return "performer", local_id, identifier, name, scenes, head, unchanged, deep_scan_due, None
                except Exception as exc:
                    return "performer", local_id, identifier, name, [], (), False, deep_scan_due, exc

        async def scan_studio(local_id, identifier, name, previous_head, deep_scan_due):
            async with semaphore:
                try:
                    scenes, head, unchanged = await _studio_scan(
                        tpdb,
                        identifier,
                        previous_head,
                        force_deep=deep_scan_due,
                    )
                    return "studio", local_id, identifier, name, scenes, head, unchanged, deep_scan_due, None
                except Exception as exc:
                    return "studio", local_id, identifier, name, [], (), False, deep_scan_due, exc

        tasks = [scan_performer(*row) for row in performers]
        tasks.extend(scan_studio(*row) for row in studios)
        scan_results = await asyncio.gather(*tasks) if tasks else []

    for kind, local_id, identifier, name, scenes, head, unchanged, deep_scanned, error in scan_results:
        if error is not None:
            errors.append({"type": kind, "id": identifier, "name": name, "error": str(error)})
            continue
        if unchanged:
            unchanged_entities += 1
            continue
        cursor_updates.append((kind, local_id, head))
        if kind == "studio" and deep_scanned:
            studio_deep_scan_updates.append(local_id)
        if kind == "performer" and deep_scanned:
            performer_deep_scan_updates.append(local_id)
        for scene in scenes:
            discovered[scene.id] = scene

    created, refreshed, persisted_scene_ids, persistence_errors = await asyncio.to_thread(
        _persist_discovered_scenes,
        session_factory,
        discovered,
        cursor_updates,
        studio_deep_scan_updates,
        performer_deep_scan_updates,
    )
    candidate_scene_ids.update(persisted_scene_ids)
    errors.extend(persistence_errors)

    return {
        "entities_checked": len(performers) + len(studios),
        "performers_checked": len(performers),
        "studios_checked": len(studios),
        "unchanged_entities": unchanged_entities,
        "unique_scenes": len(discovered),
        "scene_ids": sorted(candidate_scene_ids),
        "created": created,
        "refreshed": refreshed,
        "errors": errors,
    }