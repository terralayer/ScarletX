from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from sqlalchemy import select

from .config import Settings
from .library_management import FileImportError, ensure_library_config, import_media_file
from .metadata import MetadataProviderError, metadata_client
from .media_library import index_media_file_by_id
from .models import (
    History,
    NativeUsenetJob,
    ReleaseBlocklist,
    Scene,
    TrackedDownload,
    TrackedDownloadMeta,
    utcnow,
)
from .notifications import emit_webhooks
from .services import upsert_scene

PENDING = {"queued", "downloading", "paused", "postprocessing", "import_pending"}


def _history_status(slot):
    return str(slot.get("status") or slot.get("stage") or "").strip()


def _history_path(slot):
    for key in ("storage", "path", "output", "completed_dir"):
        if slot.get(key):
            return str(slot[key])
    return None


def _block_failed(db, tracked, meta, reason):
    existing = db.scalar(
        select(ReleaseBlocklist)
        .where(
            ReleaseBlocklist.indexer == tracked.indexer,
            ReleaseBlocklist.release_title == tracked.release_title,
        )
        .limit(1)
    )
    if existing is None:
        db.add(
            ReleaseBlocklist(
                indexer=tracked.indexer,
                guid=meta.release_guid if meta else None,
                release_title=tracked.release_title,
                scene_id=tracked.scene_id,
                reason=reason[:1000],
            )
        )


async def _fetch(settings, identifier, metadata_factory):
    async with metadata_factory(settings) as metadata:
        return await metadata.get_scene(identifier)


def _native_states(db, jobs):
    states = {}
    for job in jobs:
        native = db.get(NativeUsenetJob, job["external_id"])
        if not native:
            continue
        status = native.status
        states[job["tracked_id"]] = {
            "client": "scarletx",
            "status": status,
            "completed": status == "completed",
            "failed": status in {"failed", "cancelled"},
            "path": native.output_path,
            "error": native.error or ("Download was cancelled" if status == "cancelled" else ""),
        }
    return states


async def process_completed_downloads(
    session_factory,
    settings: Settings,
    *,
    metadata_factory=metadata_client,
):
    if not settings.completed_download_import_enabled:
        return {"enabled": False, "checked": 0, "imported": 0, "failed": 0, "poll_seconds": settings.download_poll_seconds}

    with session_factory() as db:
        pending = db.scalars(select(TrackedDownload).where(TrackedDownload.status.in_(PENDING))).all()
        jobs = []
        for tracked in pending:
            meta = db.get(TrackedDownloadMeta, tracked.id)
            jobs.append(
                {
                    "tracked_id": tracked.id,
                    "external_id": tracked.nzo_id,
                    "client": "scarletx",
                }
            )
        native_jobs = [item for item in jobs if item["client"] == "scarletx"]
        states = _native_states(db, native_jobs)

    if not jobs:
        return {"enabled": True, "checked": 0, "imported": 0, "failed": 0, "poll_seconds": settings.download_poll_seconds}

    imported = failed = 0
    notifications = []
    for job in jobs:
        state = states.get(job["tracked_id"])
        if not state:
            continue
        with session_factory() as db:
            tracked = db.get(TrackedDownload, job["tracked_id"])
            meta = db.get(TrackedDownloadMeta, tracked.id) if tracked else None
            if not tracked:
                continue
            tracked.client_status = state["status"]
            tracked.last_checked_at = utcnow()
            if state["failed"]:
                tracked.status = "failed"
                tracked.error = state["error"] or f"Download status: {state['status']}"
                _block_failed(db, tracked, meta, tracked.error)
                db.add(History(event_type="download_failed", scene_id=tracked.scene_id, message=f"Download failed: {tracked.release_title}"))
                db.commit()
                failed += 1
                notifications.append(("failed", {"scene_id": tracked.scene_id, "release_title": tracked.release_title, "error": tracked.error}))
                continue
            if not state["completed"]:
                tracked.status = "downloading" if state["status"] not in {"queued", "paused"} else state["status"]
                db.commit()
                continue
            storage_path = state["path"]
            tracked.storage_path = storage_path
            tracked.status = "import_pending"
            tracked.completed_at = tracked.completed_at or utcnow()
            metadata_id = tracked.scene_tpdb_id
            local_scene = db.get(Scene, tracked.scene_id) if tracked.scene_id else None
            release_title = tracked.release_title
            download_client = state["client"]
            db.commit()

        try:
            local_scene_id = local_scene.id if local_scene and local_scene.content_type == "scene" else None
            if local_scene_id is None:
                if not metadata_id:
                    with session_factory() as db:
                        tracked = db.get(TrackedDownload, job["tracked_id"])
                        tracked.error = "Completed download is not linked to a scene"
                        db.commit()
                    continue
                remote = await _fetch(settings, metadata_id, metadata_factory)
                with session_factory() as db:
                    local_scene = upsert_scene(db, remote, True, "scene")
                    local_scene_id = local_scene.id
            with session_factory() as db:
                tracked = db.get(TrackedDownload, job["tracked_id"])
                scene = db.get(Scene, local_scene_id)
                if not tracked or not scene:
                    continue
                tracked.scene_id = scene.id
                ensure_library_config(db, scene)
                moved = None
                media_id = None
                # ScarletX's built-in downloader owns its completed payload and should
                # always finish the job by placing the primary scene in the configured
                # library. The legacy File Management toggle remains meaningful for
                # external clients, but must not leave native downloads as hash/PAR/RAR
                # payload directories in Completed.
                if settings.file_management_enabled or download_client == "scarletx":
                    if not storage_path:
                        raise FileImportError("Download client did not report a completed storage path")
                    media = import_media_file(
                        db,
                        scene=scene,
                        release_title=release_title,
                        storage_path=storage_path,
                        settings=settings,
                    )
                    moved = media.path
                    media_id = media.id
                tracked.status = "imported"
                tracked.imported_at = utcnow()
                tracked.error = None
                if moved and download_client == "scarletx":
                    native = db.get(NativeUsenetJob, tracked.nzo_id)
                    if native is not None:
                        native.output_path = moved
                        note = native.postprocess_note or "Download complete"
                        native.postprocess_note = (note + f"; Imported scene: {Path(moved).name}")[:2000]
                label = "ScarletX Built-In"
                msg = f"Imported {scene.title} after {label} completed {release_title}" + (f" -> {moved}" if moved else "")
                db.add(History(event_type="download_imported", scene_id=scene.id, message=msg))
                db.commit()
                # Native Usenet has no seeding requirement. Once the selected video
                # has been moved into the library, discard PAR2/RAR/hash support files.
                if moved and storage_path and download_client == "scarletx":
                    source_root = Path(storage_path).expanduser()
                    try:
                        if source_root.is_dir() and not Path(moved).resolve().is_relative_to(source_root.resolve()):
                            shutil.rmtree(source_root, ignore_errors=True)
                    except OSError:
                        pass
                imported += 1
                notifications.append(("import", {"scene_id": scene.id, "title": scene.title, "release_title": release_title, "path": moved}))
            if media_id is not None:
                await asyncio.to_thread(index_media_file_by_id, session_factory, media_id, generate_art=True)
        except (FileImportError, MetadataProviderError) as exc:
            with session_factory() as db:
                tracked = db.get(TrackedDownload, job["tracked_id"])
                if tracked:
                    tracked.status = "import_pending"
                    tracked.error = str(exc)[:2000]
                    tracked.last_checked_at = utcnow()
                    db.commit()

    for event, payload in notifications:
        await emit_webhooks(session_factory, event, payload)
    return {"enabled": True, "checked": len(states), "imported": imported, "failed": failed, "poll_seconds": settings.download_poll_seconds}
