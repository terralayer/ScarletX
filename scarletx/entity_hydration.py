from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from .automation import search_and_grab_scene
from .config import Settings
from .db import SessionLocal
from .library_management import ensure_library_config
from .metadata import MetadataProviderError, metadata_client
from .models import BackgroundJob, History, utcnow
from .schemas import RemoteScene
from .services import upsert_scene

ENTITY_PAGE_SIZE = 100
ENTITY_PAGE_TIMEOUT_SECONDS = 25
ENTITY_DETAIL_CONCURRENCY = 3
ENTITY_FETCH_ATTEMPTS = 3
ENTITY_RETRY_DELAY_SECONDS = 1.0
DETAIL_BATCH_SIZE = 100
MAX_ENTITY_PAGES = 1000


async def _fetch_with_retry(operation, label: str):
    last_error: Exception | None = None
    for attempt in range(1, ENTITY_FETCH_ATTEMPTS + 1):
        try:
            return await asyncio.wait_for(operation(), timeout=ENTITY_PAGE_TIMEOUT_SECONDS)
        except (TimeoutError, MetadataProviderError) as exc:
            last_error = exc
            if attempt < ENTITY_FETCH_ATTEMPTS:
                await asyncio.sleep(ENTITY_RETRY_DELAY_SECONDS * attempt)
    raise MetadataProviderError(f"{label} failed after {ENTITY_FETCH_ATTEMPTS} attempts: {last_error}")


async def _entity_scene_summaries(tpdb, entity_type: str, identifier: str) -> list[RemoteScene]:
    """Fetch every TPDB scene credited to a performer or studio."""
    scenes: list[RemoteScene] = []
    seen: set[str] = set()

    if entity_type == "performer":
        async def fetch(page: int):
            return await tpdb.get_performer_scenes(identifier, page=page, per_page=ENTITY_PAGE_SIZE)
    elif entity_type == "studio":
        studio = await _fetch_with_retry(lambda: tpdb.get_studio(identifier), f"TPDB studio {identifier}")
        search_id = studio.search_id
        if search_id is None and identifier.isdigit():
            search_id = int(identifier)
        if search_id is None:
            raise MetadataProviderError("TPDB studio has no searchable ID")

        async def fetch(page: int):
            return await tpdb.search_scenes(page=page, per_page=ENTITY_PAGE_SIZE, site_id=str(search_id))
    else:
        raise ValueError("Unsupported adult entity type")

    page = 1
    while page <= MAX_ENTITY_PAGES:
        result = await _fetch_with_retry(lambda page=page: fetch(page), f"TPDB scene page {page}")
        for remote in result.items:
            if remote.id in seen:
                continue
            seen.add(remote.id)
            scenes.append(remote)

        if page * ENTITY_PAGE_SIZE >= result.total:
            return scenes
        page += 1

    raise MetadataProviderError(f"TPDB entity scene list exceeded {MAX_ENTITY_PAGES} pages")


async def _full_scene_details(tpdb, summaries: list[RemoteScene]) -> list[RemoteScene]:
    """Hydrate full scene detail so every performer/studio credit is cached."""
    semaphore = asyncio.Semaphore(ENTITY_DETAIL_CONCURRENCY)

    async def detail(summary: RemoteScene) -> RemoteScene:
        async with semaphore:
            async def load():
                return await tpdb.get_scene(summary.id)
            return await _fetch_with_retry(load, f"TPDB scene {summary.id} detail")

    details: list[RemoteScene] = []
    for start in range(0, len(summaries), DETAIL_BATCH_SIZE):
        batch = summaries[start:start + DETAIL_BATCH_SIZE]
        details.extend(await asyncio.gather(*(detail(summary) for summary in batch)))
    return details


async def fetch_entity_scene_graph(
    settings: Settings,
    entity_type: str,
    identifier: str,
) -> list[RemoteScene]:
    """Return the complete TPDB scene graph for an added performer/studio."""
    async with metadata_client(settings) as tpdb:
        summaries = await _entity_scene_summaries(tpdb, entity_type, identifier)
        return await _full_scene_details(tpdb, summaries)


def _job_search_requested(job_id: int, initial: bool) -> bool:
    """Honor a monitor upgrade made while an existing hydration job is running."""
    if initial:
        return True
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            return False
        try:
            payload = json.loads(job.payload or "{}")
        except (TypeError, json.JSONDecodeError):
            return False
        return bool(payload.get("search_when_monitored"))


async def run_adult_entity_hydration(
    job_id: int,
    entity_type: str,
    identifier: str,
    settings: Settings,
    search_when_monitored: bool,
) -> None:
    """Cache a complete TPDB graph, then search hydrated scenes when monitored."""
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

    try:
        remote_scenes = await fetch_entity_scene_graph(settings, entity_type, identifier)
        effective_search_when_monitored = _job_search_requested(job_id, search_when_monitored)
        scene_ids: list[int] = []
        performer_ids: set[str] = set()
        studio_ids: set[str] = set()

        # Cache the complete graph in one transaction instead of one SQLite commit per scene.
        with SessionLocal() as db:
            for remote in remote_scenes:
                scene = upsert_scene(db, remote, monitored=False, content_type="scene", commit=False)
                if effective_search_when_monitored:
                    scene.monitored = True
                ensure_library_config(db, scene)
                scene_ids.append(scene.id)
                performer_ids.update(item.id for item in remote.performers)
                if remote.studio is not None:
                    studio_ids.add(remote.studio.id)
            db.commit()

            job = db.get(BackgroundJob, job_id)
            if job is not None:
                job.payload = json.dumps({
                    "entity_type": entity_type,
                    "identifier": identifier,
                    "scenes_cached": len(scene_ids),
                    "performers_cached": len(performer_ids),
                    "studios_cached": len(studio_ids),
                    "search_when_monitored": effective_search_when_monitored,
                })
                db.commit()

        search_counts: dict[str, int] = {}
        if effective_search_when_monitored:
            for position, scene_id in enumerate(scene_ids, start=1):
                result = await search_and_grab_scene(SessionLocal, scene_id, settings)
                search_counts[result.status] = search_counts.get(result.status, 0) + 1
                with SessionLocal() as db:
                    job = db.get(BackgroundJob, job_id)
                    if job is not None:
                        payload = json.loads(job.payload or "{}")
                        payload["scenes_searched"] = position
                        payload["search_results"] = search_counts
                        job.payload = json.dumps(payload)
                        db.commit()

        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                payload = json.loads(job.payload or "{}")
                payload["search_results"] = search_counts
                job.payload = json.dumps(payload)
                job.status = "completed"
                job.finished_at = utcnow()
                db.add(History(
                    event_type=f"{entity_type}_metadata_hydration",
                    message=(
                        f"Cached {len(scene_ids)} scenes, {len(performer_ids)} performers, "
                        f"and {len(studio_ids)} studios for {entity_type} {identifier}"
                    ),
                ))
                db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error = str(exc)[:1000]
                job.finished_at = utcnow()
                db.commit()


def queue_adult_entity_hydration(
    db,
    tasks,
    entity_type: str,
    identifier: str,
    settings: Settings,
    *,
    search_when_monitored: bool,
) -> int:
    """Queue one durable hydration job per active entity add."""
    kind = f"{entity_type}_metadata_hydration"
    active_jobs = db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.kind == kind,
            BackgroundJob.status.in_(("queued", "running")),
        ).order_by(BackgroundJob.created_at.desc())
    ).all()
    for active in active_jobs:
        try:
            payload = json.loads(active.payload or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("identifier") == identifier:
            # A running cache-only job observes this payload update before its search phase.
            if search_when_monitored and not payload.get("search_when_monitored"):
                payload["search_when_monitored"] = True
                active.payload = json.dumps(payload)
                db.commit()
            return active.id

    job = BackgroundJob(
        kind=kind,
        payload=json.dumps({
            "entity_type": entity_type,
            "identifier": identifier,
            "search_when_monitored": search_when_monitored,
        }),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    tasks.add_task(
        run_adult_entity_hydration,
        job.id,
        entity_type,
        identifier,
        settings,
        search_when_monitored,
    )
    return job.id
