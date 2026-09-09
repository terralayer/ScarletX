from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Scene
from .remote_art import (
    RemoteArtworkError,
    cache_remote_image_bytes,
    cached_remote_image,
    cached_remote_thumbnail,
)
from .studio_art import StudioArtworkError, cache_studio_artwork, prepare_studio_artwork


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
    scene_cached: dict[str, tuple[bytes, str, str]] = {}
    for kind, url in scene_sources:
        if not url:
            continue
        try:
            payload, content_type = await cached_remote_image(
                f"scene:{scene_id_key}:{kind}", [url]
            )
            scene_cached[kind] = (payload, content_type, url)
            stats["scene_images"] += 1
        except RemoteArtworkError:
            stats["errors"] += 1

    # Seed the exact route cache from bytes already fetched above, so the first UI
    # request cannot trigger a second network transfer of the preferred scene image.
    for preferred in ("back", "image", "poster"):
        cached = scene_cached.get(preferred)
        if cached is None:
            continue
        payload, content_type, source_url = cached
        cache_remote_image_bytes(
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

    for performer in scene.performers:
        if not performer.image_url:
            continue
        performer_key = str(performer.tpdb_id or performer.id)
        try:
            await cached_remote_image(
                f"performer:{performer_key}", [performer.image_url]
            )
            stats["performer_images"] += 1
            await cached_remote_thumbnail(
                f"performer:{performer_key}",
                [performer.image_url],
                (320, 480),
                contain=True,
            )
        except RemoteArtworkError:
            stats["errors"] += 1

    studio = scene.studio
    if studio is not None:
        studio_key = str(studio.tpdb_id or studio.id)
        studio_sources = [
            ("logo", studio.logo_url),
            ("poster", studio.poster_url),
        ]
        preferred_payload: bytes | None = None
        for kind, url in studio_sources:
            if not url:
                continue
            try:
                payload, _content_type = await cached_remote_image(
                    f"studio:{studio_key}:{kind}", [url]
                )
                stats["studio_images"] += 1
                if preferred_payload is None:
                    preferred_payload = payload
            except RemoteArtworkError:
                stats["errors"] += 1
        if preferred_payload is not None:
            try:
                cache_studio_artwork(
                    studio_key, prepare_studio_artwork(preferred_payload)
                )
            except StudioArtworkError:
                stats["errors"] += 1

    return stats
