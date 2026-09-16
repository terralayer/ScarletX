from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import exists, func, or_, select

from .library_management import (
    QUALITY_ORDER,
    default_quality_profile,
    detect_quality,
    ensure_library_config,
)
from .models import (
    History,
    LibraryItemConfig,
    MediaFile,
    Performer,
    QualityProfile,
    RootFolder,
    Scene,
    Studio,
    TrackedDownload,
    scene_performer,
)

_SEARCH_EVENT_TYPES = (
    "scene_monitor_search",
    "scene_search",
    "manual_search",
    "automatic_search",
)
_ACTIVE_DOWNLOAD_STATES = {"queued", "downloading", "postprocessing", "paused"}


def _profile_for(db, scene):
    cfg = ensure_library_config(db, scene)
    if cfg.quality_profile_id:
        return db.get(QualityProfile, cfg.quality_profile_id)
    return default_quality_profile(db, "scene")


def _wanted_state(
    *,
    status: str | None,
    error: str | None,
    last_search_at,
) -> tuple[str, str, int | None, bool]:
    normalized = str(status or "").strip().casefold()
    detail = str(error or "").strip()

    if normalized in _ACTIVE_DOWNLOAD_STATES:
        labels = {
            "queued": "Download queued",
            "downloading": "Download in progress",
            "postprocessing": "Download complete; processing media",
            "paused": "Download paused",
        }
        return normalized, labels[normalized], 1, True

    if normalized in {"completed", "complete", "downloaded"}:
        return "downloaded", "Download complete; awaiting import", 1, False

    if normalized in {"failed", "error"}:
        if "import failed" in detail.casefold():
            return "failed_import", detail or "Import failed", 1, False
        return "download_failed", detail or "Download failed", 1, False

    if normalized in {"cancelled", "canceled"}:
        return "cancelled", "Download cancelled", 1, False

    if last_search_at is not None:
        return "no_result", "Search returned no downloadable release", 0, False

    return "never_searched", "Never searched", None, False


def missing_items(db, content_type=None, limit=500):
    target_type = content_type or "scene"

    last_search_at = (
        select(func.max(History.created_at))
        .where(
            History.scene_id == Scene.id,
            History.event_type.in_(_SEARCH_EVENT_TYPES),
        )
        .correlate(Scene)
        .scalar_subquery()
    )
    latest_status = (
        select(func.coalesce(TrackedDownload.client_status, TrackedDownload.status))
        .where(TrackedDownload.scene_id == Scene.id)
        .order_by(TrackedDownload.created_at.desc(), TrackedDownload.id.desc())
        .limit(1)
        .correlate(Scene)
        .scalar_subquery()
    )
    latest_error = (
        select(TrackedDownload.error)
        .where(TrackedDownload.scene_id == Scene.id)
        .order_by(TrackedDownload.created_at.desc(), TrackedDownload.id.desc())
        .limit(1)
        .correlate(Scene)
        .scalar_subquery()
    )

    rows = db.execute(
        select(
            Scene.id,
            Scene.title,
            Scene.release_date,
            Scene.tpdb_id,
            last_search_at.label("last_search_at"),
            latest_status.label("download_status"),
            latest_error.label("download_error"),
        )
        .where(
            Scene.monitored.is_(True),
            Scene.content_type == target_type,
            ~exists(select(MediaFile.id).where(MediaFile.scene_id == Scene.id)),
        )
        .order_by(Scene.release_date, Scene.title)
        .limit(limit)
    ).all()

    wanted = []
    for row in rows:
        state, reason, result_count, active = _wanted_state(
            status=row.download_status,
            error=row.download_error,
            last_search_at=row.last_search_at,
        )
        wanted.append(
            {
                "kind": "scene",
                "library_item_id": row.id,
                "title": row.title,
                "release_date": row.release_date,
                "metadata_id": row.tpdb_id,
                "state": state,
                "reason": reason,
                "last_search_at": row.last_search_at,
                "result_count": result_count,
                "active": active,
            }
        )
    return wanted


def cutoff_unmet(db, content_type=None, limit=500):
    scenes = db.scalars(
        select(Scene).where(Scene.monitored.is_(True), Scene.content_type == "scene")
    ).all()
    if not scenes:
        return []
    configs = {
        item.scene_id: item
        for item in db.scalars(
            select(LibraryItemConfig)
            .join(Scene, Scene.id == LibraryItemConfig.scene_id)
            .where(Scene.monitored.is_(True), Scene.content_type == "scene")
        ).all()
    }
    profiles = {item.id: item for item in db.scalars(select(QualityProfile)).all()}
    default = default_quality_profile(db, "scene")
    files_by_scene = {}
    for media in db.scalars(
        select(MediaFile)
        .join(Scene, Scene.id == MediaFile.scene_id)
        .where(Scene.monitored.is_(True), Scene.content_type == "scene")
    ).all():
        files_by_scene.setdefault(media.scene_id, []).append(media)
    rows = []
    for scene in scenes:
        config = configs.get(scene.id)
        profile = (
            profiles.get(config.quality_profile_id)
            if config and config.quality_profile_id
            else default
        )
        if not profile:
            continue
        files = files_by_scene.get(scene.id, [])
        if not files:
            continue
        best = max(
            files,
            key=lambda x: QUALITY_ORDER.get(
                detect_quality(x.quality or x.release_title or "").resolution,
                0,
            ),
        )
        current = detect_quality(best.quality or best.release_title or "").resolution
        if QUALITY_ORDER.get(current, 0) < QUALITY_ORDER.get(
            profile.cutoff_quality.casefold(), 0
        ):
            rows.append(
                {
                    "kind": "scene",
                    "library_item_id": scene.id,
                    "title": scene.title,
                    "current_quality": current,
                    "cutoff": profile.cutoff_quality,
                }
            )
        if len(rows) >= limit:
            break
    return rows


def calendar_items(db, start, end, limit=500):
    rows = []
    monitored_performer = exists(
        select(scene_performer.c.scene_id)
        .join(Performer, Performer.id == scene_performer.c.performer_id)
        .where(
            scene_performer.c.scene_id == Scene.id,
            Performer.monitored.is_(True),
        )
    )
    stmt = (
        select(Scene)
        .where(
            Scene.content_type == "scene",
            or_(
                Scene.monitored.is_(True),
                Scene.studio.has(Studio.monitored.is_(True)),
                monitored_performer,
            ),
            Scene.release_date >= start,
            Scene.release_date <= end,
        )
        .order_by(Scene.release_date, Scene.title)
        .limit(limit)
    )
    for scene in db.scalars(stmt).all():
        rows.append(
            {
                "date": scene.release_date,
                "kind": "scene",
                "library_item_id": scene.id,
                "title": scene.title,
                "monitored": True,
            }
        )
    return rows


def disk_space(db):
    rows = []
    roots = db.scalars(
        select(RootFolder)
        .where(RootFolder.content_type == "scene")
        .order_by(RootFolder.name)
    ).all()
    for root in roots:
        path = Path(root.path).expanduser()
        if not path.exists():
            rows.append(
                {
                    "root_folder_id": root.id,
                    "name": root.name,
                    "content_type": "scene",
                    "path": root.path,
                    "exists": False,
                }
            )
            continue
        try:
            usage = shutil.disk_usage(path)
            rows.append(
                {
                    "root_folder_id": root.id,
                    "name": root.name,
                    "content_type": "scene",
                    "path": root.path,
                    "exists": True,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "free_percent": round(
                        (usage.free / usage.total * 100) if usage.total else 0,
                        1,
                    ),
                }
            )
        except OSError as exc:
            rows.append(
                {
                    "root_folder_id": root.id,
                    "name": root.name,
                    "content_type": "scene",
                    "path": root.path,
                    "exists": True,
                    "error": str(exc),
                }
            )
    return rows
