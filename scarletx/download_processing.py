from __future__ import annotations

import asyncio
import re
import shutil
from datetime import UTC, timedelta
from pathlib import Path
from sqlalchemy import select

from .config import Settings
from .download_metrics import download_phase_metrics
from .library_management import FileImportError, ensure_library_config, import_media_file
from .metadata import metadata_client
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
from .recent_imports import FileIdentity, recent_imports
from .services import upsert_scene
from .status_console import emit_status

PENDING = {"queued", "downloading", "paused", "postprocessing", "import_pending"}
IMPORT_MAX_ATTEMPTS = 3
IMPORT_RETRY_DELAYS_SECONDS = (30, 120)
_IMPORT_ATTEMPT_RE = re.compile(r"^\[import-attempt\s+(\d+)/(\d+)\]\s*")


def _history_status(slot):
    return str(slot.get("status") or slot.get("stage") or "").strip()


def _history_path(slot):
    for key in ("storage", "path", "output", "completed_dir"):
        if slot.get(key):
            return str(slot[key])
    return None


def _import_failure_attempt(error: str | None) -> int:
    if not error:
        return 0
    match = _IMPORT_ATTEMPT_RE.match(str(error))
    if not match:
        return 0
    try:
        return max(0, min(int(match.group(1)), IMPORT_MAX_ATTEMPTS))
    except (TypeError, ValueError):
        return 0


def _retry_attempt_for(tracked: TrackedDownload) -> int:
    attempt = _import_failure_attempt(tracked.error)
    # Existing databases can contain pre-backoff import errors without an attempt
    # prefix. Treat those as one prior failure so an upgrade immediately stops the
    # old one-second retry storm without requiring a schema migration.
    if attempt == 0 and tracked.status == "import_pending" and tracked.error:
        return 1
    return attempt


def _aware(value):
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _import_retry_ready(tracked: TrackedDownload, *, now=None) -> bool:
    attempt = _retry_attempt_for(tracked)
    if attempt <= 0:
        return True
    if attempt >= IMPORT_MAX_ATTEMPTS:
        return False
    if tracked.last_checked_at is None:
        return True
    delay_index = min(attempt - 1, len(IMPORT_RETRY_DELAYS_SECONDS) - 1)
    retry_after = _aware(tracked.last_checked_at) + timedelta(seconds=IMPORT_RETRY_DELAYS_SECONDS[delay_index])
    return _aware(now or utcnow()) >= retry_after


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


def _pending_state_maps(db, pending):
    tracked_ids = [tracked.id for tracked in pending]
    external_ids = [tracked.nzo_id for tracked in pending if tracked.nzo_id]
    metadata_by_tracked = {
        row.tracked_download_id: row
        for row in db.scalars(
            select(TrackedDownloadMeta).where(TrackedDownloadMeta.tracked_download_id.in_(tracked_ids))
        ).all()
    } if tracked_ids else {}
    native_by_id = {
        row.id: row
        for row in db.scalars(
            select(NativeUsenetJob).where(NativeUsenetJob.id.in_(external_ids))
        ).all()
    } if external_ids else {}
    jobs = []
    states = {}
    for tracked in pending:
        jobs.append({"tracked_id": tracked.id, "external_id": tracked.nzo_id, "client": "scarletx"})
        native = native_by_id.get(tracked.nzo_id)
        if native is None:
            continue
        status = native.status
        states[tracked.id] = {
            "client": "scarletx",
            "status": status,
            "completed": status == "completed",
            "failed": status in {"failed", "cancelled"},
            "path": native.output_path,
            "error": native.error or ("Download was cancelled" if status == "cancelled" else ""),
        }
    return jobs, states, metadata_by_tracked, native_by_id


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
        jobs, states, metadata_by_tracked, native_by_id = _pending_state_maps(db, pending)

    if not jobs:
        return {"enabled": True, "checked": 0, "imported": 0, "failed": 0, "poll_seconds": settings.download_poll_seconds}

    imported = failed = 0
    notifications = []
    completed_jobs = []
    tracked_ids = [job["tracked_id"] for job in jobs]
    with session_factory() as db:
        tracked_by_id = {
            row.id: row for row in db.scalars(
                select(TrackedDownload).where(TrackedDownload.id.in_(tracked_ids))
            ).all()
        } if tracked_ids else {}
        for job in jobs:
            state = states.get(job["tracked_id"])
            tracked = tracked_by_id.get(job["tracked_id"])
            if not state or not tracked:
                continue
            tracked.client_status = state["status"]
            if state["failed"]:
                tracked.last_checked_at = utcnow()
                tracked.status = "failed"
                tracked.error = state["error"] or f"Download status: {state['status']}"
                _block_failed(db, tracked, metadata_by_tracked.get(tracked.id), tracked.error)
                db.add(History(event_type="download_failed", scene_id=tracked.scene_id, message=f"Download failed: {tracked.release_title}"))
                failed += 1
                notifications.append(("failed", {"scene_id": tracked.scene_id, "release_title": tracked.release_title, "error": tracked.error}))
                continue
            if not state["completed"]:
                tracked.last_checked_at = utcnow()
                tracked.status = "downloading" if state["status"] not in {"queued", "paused"} else state["status"]
                continue
            if tracked.status == "import_pending" and not _import_retry_ready(tracked):
                continue
            completed_jobs.append(job)
        db.commit()

    for job in completed_jobs:
        state = states[job["tracked_id"]]
        with session_factory() as db:
            tracked = db.get(TrackedDownload, job["tracked_id"])
            if not tracked:
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

        emit_status("Download", "COMPLETED", release_title, severity="ok")
        emit_status("Import", "PROCESSING", release_title, severity="active")
        try:
            local_scene_id = local_scene.id if local_scene and local_scene.content_type == "scene" else None
            if local_scene_id is None:
                if not metadata_id:
                    raise FileImportError("Completed download is not linked to a scene")
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
                    with download_phase_metrics.start(str(tracked.nzo_id), "import"):
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
                if moved:
                    try:
                        recent_imports.register(FileIdentity.from_path(moved))
                    except OSError:
                        # The durable import is already complete. A disappearing
                        # destination should be reconciled normally by the scanner.
                        pass
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
                emit_status("Import", "COMPLETED", moved or release_title, severity="ok")
            if media_id is not None:
                await asyncio.to_thread(index_media_file_by_id, session_factory, media_id, generate_art=True)
        except Exception as exc:
            detail = f"{exc.__class__.__name__}: {exc}"[:1200]
            with session_factory() as db:
                tracked = db.get(TrackedDownload, job["tracked_id"])
                if tracked:
                    attempt = min(_retry_attempt_for(tracked) + 1, IMPORT_MAX_ATTEMPTS)
                    if attempt >= IMPORT_MAX_ATTEMPTS:
                        tracked.status = "import_failed"
                    else:
                        tracked.status = "import_pending"
                    tracked.error = f"[import-attempt {attempt}/{IMPORT_MAX_ATTEMPTS}] {detail}"[:2000]
                    tracked.last_checked_at = utcnow()
                    db.add(History(
                        event_type="download_import_failed",
                        scene_id=tracked.scene_id,
                        message=f"Import failed ({attempt}/{IMPORT_MAX_ATTEMPTS}): {release_title} | {detail}"[:1000],
                    ))
                    db.commit()
                    emit_status("Import", "FAILED", f"{release_title} | attempt {attempt}/{IMPORT_MAX_ATTEMPTS} | {detail}", severity="error")
            failed += 1

    for event, payload in notifications:
        try:
            await emit_webhooks(session_factory, event, payload)
        except Exception:
            # Notification transport is best effort and must not change durable
            # download/import outcomes or turn Process Completed into HTTP 500.
            continue
    return {"enabled": True, "checked": len(states), "imported": imported, "failed": failed, "poll_seconds": settings.download_poll_seconds}
