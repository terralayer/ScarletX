"""Read-only storage, backup and cleanup summaries."""

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
import shutil
import time

from sqlalchemy import func, select

from .models import BackupRecord, MediaFile, MediaProbe, RootFolder, Scene, UnmatchedMediaFile


def folder_usage(path, *, max_files=50000, seconds=1):
    path = Path(path).expanduser()
    if not path.is_dir():
        return dict(bytes=None, complete=False, error="Directory unavailable")
    pending = [path]
    size = count = 0
    deadline = time.monotonic() + seconds
    try:
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    count += 1
                    if count > max_files or time.monotonic() >= deadline:
                        return dict(bytes=size, complete=False, error="Partial count: scan limit reached")
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        size += entry.stat(follow_symlinks=False).st_size
    except OSError:
        return dict(bytes=size, complete=False, error="Partial count: a directory could not be read")
    return dict(bytes=size, complete=True, error=None)


def storage_overview(db, settings):
    backup = settings.backup_directory
    if backup in {"backups", "./backups"}:
        backup = os.getenv("SCARLETX_BACKUP_DIR", backup)
    paths = [
        ("Active downloads", settings.native_usenet_incomplete_dir),
        ("Completed downloads", settings.native_usenet_complete_dir),
        ("Backups", backup),
        ("Artwork cache", str(Path(os.getenv("SCARLETX_CACHE_DIR", "./cache")) / "tpdb" / "images")),
    ]
    paths += [
        ("Media: " + row.name, row.path) for row in db.scalars(select(RootFolder).order_by(RootFolder.id))
    ]
    rows = []
    # One shared budget across all categories; no unbounded recursive disk scan.
    deadline = time.monotonic() + 2
    for label, raw in paths:
        path = Path(raw).expanduser()
        row = dict(name=label, path=str(path), total_bytes=None, used_bytes=None, free_bytes=None)
        try:
            usage = shutil.disk_usage(path)
            row.update(total_bytes=usage.total, used_bytes=usage.used, free_bytes=usage.free)
        except OSError:
            pass
        row["folder"] = folder_usage(path, seconds=max(0, deadline - time.monotonic()))
        rows.append(row)
    return dict(
        items=rows,
        note="Filesystem usage includes other folders. Folder counts exclude symlinks; shared filesystems must not be added together.",
    )


def backup_reminder(db, settings, now=None):
    now = now or datetime.now(UTC)
    latest = db.scalar(
        select(BackupRecord).order_by(BackupRecord.created_at.desc(), BackupRecord.id.desc()).limit(1)
    )
    created = (
        latest.created_at.replace(tzinfo=UTC)
        if latest and latest.created_at.tzinfo is None
        else (latest.created_at if latest else None)
    )
    due = created + timedelta(hours=settings.backup_interval_hours) if created else None
    if not settings.backup_enabled:
        state, message = "disabled", "Automatic backups are off."
    elif latest is None:
        state, message = "never", "No successful backup has been recorded."
    elif not Path(latest.path).is_file():
        state, message = "missing", "The latest backup file is unavailable. Check backup storage."
    elif now >= due:
        state, message = "overdue", "Your scheduled backup is overdue."
    else:
        state, message = "healthy", "Your latest backup is up to date."
    return dict(
        state=state,
        message=message,
        last_success_at=created,
        next_due_at=due,
        enabled=settings.backup_enabled,
    )


def cleanup_preview(db, category, limit=50, offset=0):
    if category == "unmatched":
        stmt = select(
            UnmatchedMediaFile.id, UnmatchedMediaFile.path, UnmatchedMediaFile.display_name.label("title")
        ).order_by(UnmatchedMediaFile.id)
    else:
        stmt = (
            select(MediaFile.id, MediaFile.path, Scene.title, MediaProbe.fingerprint)
            .join(Scene, Scene.id == MediaFile.scene_id)
            .join(MediaProbe, MediaProbe.media_file_id == MediaFile.id)
        )
        if category == "missing":
            stmt = stmt.where(MediaProbe.missing.is_(True))
        elif category == "duplicates":
            groups = (
                select(MediaProbe.fingerprint)
                .where(MediaProbe.fingerprint.is_not(None), MediaProbe.missing.is_(False))
                .group_by(MediaProbe.fingerprint)
                .having(func.count() > 1)
            )
            stmt = stmt.where(MediaProbe.fingerprint.in_(groups), MediaProbe.missing.is_(False))
        else:
            raise ValueError("Unknown cleanup category")
        stmt = stmt.order_by(MediaFile.id)
    rows = db.execute(stmt.offset(offset).limit(limit + 1)).mappings().all()
    return dict(
        items=[dict(row) for row in rows[:limit]],
        has_more=len(rows) > limit,
        offset=offset,
        limit=limit,
        note="Preview only. Potential duplicates share a partial fingerprint; verify their contents before taking action. No files or records are changed.",
    )
