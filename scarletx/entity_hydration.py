from __future__ import annotations

import asyncio
import json

from sqlalchemy import select

from .automation import search_and_grab_scene
from .config import Settings
from .db import SessionLocal
from .library_management import ensure_library_config
from .metadata import MetadataProviderError, metadata_client
from .models import BackgroundJob, History, Scene, Studio, utcnow
from .schemas import RemoteScene
from .services import upsert_scene
from .studio_policy import is_allowed_remote_scene

ENTITY_PAGE_SIZE = 100
ENTITY_PAGE_TIMEOUT_SECONDS = 25
ENTITY_DETAIL_CONCURRENCY = 3
ENTITY_FETCH_ATTEMPTS = 3
ENTITY_RETRY_DELAY_SECONDS = 1.0
DETAIL_BATCH_SIZE = 25
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


def cache_entity_scene_summaries(summaries: list[RemoteScene], monitored: bool) -> list[int]:
    """Persist lightweight scene/studio metadata immediately without erasing credits."""
    scene_ids: list[int] = []
    with SessionLocal() as db:
        for remote in summaries:
            if not is_allowed_remote_scene(remote):
                continue
            scene = db.scalar(select(Scene).where(Scene.tpdb_id == remote.id))
            if scene is None:
                scene = Scene(tpdb_id=remote.id, title=remote.title, content_type="scene", monitored=monitored)
                db.add(scene)
            scene.title = remote.title
            scene.description = remote.description
            scene.release_date = remote.release_date
            scene.duration = remote.duration
            scene.source_url = remote.source_url
            scene.image_url = remote.image_url
            scene.back_image_url = remote.back_image_url
            scene.poster_url = remote.poster_url
            if monitored:
                scene.monitored = True
            if remote.studio is not None:
                studio = db.scalar(select(Studio).where(Studio.tpdb_id == remote.studio.id))
                if studio is None:
                    studio = Studio(tpdb_id=remote.studio.id, name=remote.studio.name)
                    db.add(studio)
                studio.name = remote.studio.name
                studio.url = remote.studio.url
                studio.logo_url = remote.studio.logo_url
                studio.poster_url = remote.studio.poster_url
                studio.description = remote.studio.description
                studio.is_library = True
                scene.studio = studio
            db.flush()
            ensure_library_config(db, scene)
            scene_ids.append(scene.id)
        db.commit()
    return scene_ids


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
        effective_search_when_monitored = _job_search_requested(job_id, search_when_monitored)
        scene_ids: list[int] = []
        performer_ids: set[str] = set()
        studio_ids: set[str] = set()
        skipped_policy = 0
        details_cached = 0

        async with metadata_client(settings) as tpdb:
            summaries = await _entity_scene_summaries(tpdb, entity_type, identifier)
            summary_ids = cache_entity_scene_summaries(summaries, effective_search_when_monitored)
            with SessionLocal() as db:
                job = db.get(BackgroundJob, job_id)
                if job is not None:
                    job.payload = json.dumps({
                        "entity_type": entity_type,
                        "identifier": identifier,
                        "summaries_cached": len(summary_ids),
                        "details_cached": 0,
                        "search_when_monitored": effective_search_when_monitored,
                    })
                    db.commit()

            for start in range(0, len(summaries), DETAIL_BATCH_SIZE):
                batch = summaries[start:start + DETAIL_BATCH_SIZE]
                details = await _full_scene_details(tpdb, batch)
                with SessionLocal() as db:
                    for remote in details:
                        if not is_allowed_remote_scene(remote):
                            skipped_policy += 1
                            continue
                        try:
                            scene = upsert_scene(db, remote, monitored=False, content_type="scene", commit=False)
                        except ValueError:
                            skipped_policy += 1
                            continue
                        if effective_search_when_monitored:
                            scene.monitored = True
                        ensure_library_config(db, scene)
                        scene_ids.append(scene.id)
                        performer_ids.update(item.id for item in remote.performers)
                        if remote.studio is not None:
                            studio_ids.add(remote.studio.id)
                        details_cached += 1
                    db.commit()
                    job = db.get(BackgroundJob, job_id)
                    if job is not None:
                        job.payload = json.dumps({
                            "entity_type": entity_type,
                            "identifier": identifier,
                            "summaries_cached": len(summary_ids),
                            "details_cached": details_cached,
                            "scenes_cached": len(scene_ids),
                            "performers_cached": len(performer_ids),
                            "studios_cached": len(studio_ids),
                            "skipped_policy": skipped_policy,
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
