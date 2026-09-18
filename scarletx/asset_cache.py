from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Scene
from .remote_art import (
    RemoteArtworkError,
    run_artwork_work,
    cache_remote_image_bytes,
    cached_remote_image,
    cached_remote_thumbnail,
)
from .studio_art import StudioArtworkError, cache_studio_artwork, prepare_studio_artwork


async def _bounded_map(function, items):
    results = [None] * len(items)
    pending = iter(enumerate(items))
    async def worker():
        for index, item in pending:
            results[index] = await function(item)
    async with asyncio.TaskGroup() as group:
        for _ in range(min(4, len(items))):
            group.create_task(worker())
    return results


async def cache_scene_asset_bundle(db: Session, scene_id: int) -> dict[str, int]:
    """Warm every persistent artwork cache needed to render one downloaded scene offline."""
    scene = db.scalar(
        select(Scene)
        .where(Scene.id == scene_id)
        .options(selectinload(Scene.performers), selectinload(Scene.studio))
    )
    if scene is None:
        return {"scene_images": 0, "performer_images": 0, "studio_images": 0, "errors": 0}

    stats = {"scene_images": 0, "performer_images": 0, "studio_images": 0, "errors": 0}
    scene_id_key = str(scene.tpdb_id or scene.id)
    scene_sources = [
        ("back", scene.back_image_url),
        ("image", scene.image_url),
        ("poster", scene.poster_url),
    ]
    performer_sources = [(str(item.tpdb_id or item.id), item.image_url) for item in scene.performers if item.image_url]
    studio = scene.studio
    studio_key = str(studio.tpdb_id or studio.id) if studio else None
    studio_sources = [(kind, url) for kind, url in (("logo", studio.logo_url), ("poster", studio.poster_url)) if url] if studio else []

    async def fetch_source(source):
        key, url = source
        try:
            payload, content_type = await cached_remote_image(key, [url])
            return payload, content_type, url
        except RemoteArtworkError:
            stats["errors"] += 1
            return None

    available_scene_sources = [(kind, url) for kind, url in scene_sources if url]
    fetched = await _bounded_map(fetch_source, [(f"scene:{scene_id_key}:{kind}", url) for kind, url in available_scene_sources])
    scene_cached = {kind: result for (kind, _), result in zip(available_scene_sources, fetched) if result is not None}
    stats["scene_images"] = len(scene_cached)

    # Seed the exact route cache from bytes already fetched above, so the first UI
    # request cannot trigger a second network transfer of the preferred scene image.
    for preferred in ("back", "image", "poster"):
        cached = scene_cached.get(preferred)
        if cached is None:
            continue
        payload, content_type, source_url = cached
        await run_artwork_work(cache_remote_image_bytes,
            f"scene:{scene_id_key}", payload, content_type, source_url
        )
        break

    scene_urls = [url for _kind, url in scene_sources if url]
    if scene_cached and scene_urls:
        try:
            await cached_remote_thumbnail(
                f"scene:{scene_id_key}", scene_urls, (320, 180)
            )
        except RemoteArtworkError:
            stats["errors"] += 1

    async def warm_performer(source):
        performer_key, url = source
        try:
            await cached_remote_image(f"performer:{performer_key}", [url])
            stats["performer_images"] += 1
            await cached_remote_thumbnail(f"performer:{performer_key}", [url], (320, 480), contain=True)
        except RemoteArtworkError:
            stats["errors"] += 1

    await _bounded_map(warm_performer, performer_sources)
    fetched_studio = await _bounded_map(fetch_source, [(f"studio:{studio_key}:{kind}", url) for kind, url in studio_sources])
    studio_payloads = [result[0] for result in fetched_studio if result is not None]
    stats["studio_images"] = len(studio_payloads)
    if studio_payloads:
        try:
            prepared = await run_artwork_work(prepare_studio_artwork, studio_payloads[0])
            await run_artwork_work(cache_studio_artwork, studio_key, prepared)
        except StudioArtworkError:
            stats["errors"] += 1
    return stats
