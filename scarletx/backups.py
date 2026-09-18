from __future__ import annotations

import os
from contextlib import suppress
import shutil
import sqlite3
from uuid import uuid4
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import engine
from .models import BackupRecord
from .status_console import emit_status


class BackupError(RuntimeError):
    pass


def _backup_dir(directory: str) -> Path:
    # 0.3.9 persisted the local-development default (./backups) even in
    # containers.  Honor an explicit packaging override only for that legacy
    # default; a user-selected custom directory always wins.
    requested = str(directory or "").strip()
    if requested in {"backups", "./backups"}:
        packaged = os.getenv("SCARLETX_BACKUP_DIR", "").strip()
        if packaged:
            requested = packaged
    path = Path(requested or directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secret_key_backup_path(database_path: Path) -> Path:
    return database_path.with_suffix(".secret.key")


def _copy_secret_key_for_backup(database_path: Path) -> Path | None:
    secret_key_path = Path(
        os.getenv("SCARLETX_SECRET_KEY_FILE", ".scarletx-secret.key")
    ).expanduser()
    if not secret_key_path.exists():
        return None
    target = _secret_key_backup_path(database_path)
    try:
        shutil.copy2(secret_key_path, target)
        os.chmod(target, 0o600)
    except OSError as exc:
        with suppress(OSError):
            target.unlink(missing_ok=True)
        raise BackupError(f"ScarletX secret-key backup failed: {exc}") from exc
    return target


def create_backup(db: Session, directory: str, keep: int = 14) -> BackupRecord:
    if engine.url.get_backend_name() != "sqlite":
        raise BackupError("Built-in ScarletX backup currently supports the local SQLite application database")
    source_name = engine.url.database
    if not source_name:
        raise BackupError("ScarletX SQLite database path is not available")
    source = Path(source_name)
    if not source.is_absolute():
        source = Path.cwd() / source
    try:
        target_dir = _backup_dir(directory)
    except OSError as exc:
        raise BackupError(f"ScarletX backup directory is unavailable: {exc}") from exc
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"scarletx-{timestamp}-{uuid4().hex}.db"
    emit_status("Backup", "PROCESSING", str(target), severity="active")
    try:
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
        _copy_secret_key_for_backup(target)
    except (sqlite3.Error, OSError, BackupError) as exc:
        emit_status("Backup", "FAILED", exc.__class__.__name__, severity="error")
        with suppress(OSError):
            target.unlink(missing_ok=True)
        with suppress(OSError):
            _secret_key_backup_path(target).unlink(missing_ok=True)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"ScarletX database backup failed: {exc}") from exc
    record = BackupRecord(path=str(target), size_bytes=target.stat().st_size)
    db.add(record)
    db.commit()
    db.refresh(record)
    rotate_backups(db, target_dir, keep)
    emit_status("Backup", "COMPLETED", str(target), severity="ok")
    return record


def rotate_backups(db: Session, directory: Path, keep: int) -> None:
    keep = max(1, int(keep))
    records = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc())).all()
    for record in records[keep:]:
        path = Path(record.path)
        try:
            if path.parent.resolve() == directory.resolve():
                path.unlink(missing_ok=True)
                _secret_key_backup_path(path).unlink(missing_ok=True)
        except OSError:
            continue
        db.delete(record)
    db.commit()


def list_backups(db: Session) -> list[dict]:
    rows = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc())).all()
    result = []
    for row in rows:
        path = Path(row.path)
        secret_key_path = _secret_key_backup_path(path)
        result.append(
            {
                "id": row.id,
                "path": row.path,
                "size_bytes": row.size_bytes,
                "created_at": row.created_at,
                "exists": path.exists(),
                "secret_key_path": str(secret_key_path) if secret_key_path.exists() else None,
            }
        )
    return result


def run_scheduled_backup(db, settings, now=None):
    if not settings.backup_enabled:
        return False
    now = now or datetime.now(UTC)
    latest = db.scalar(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(1))
    created = latest.created_at if latest else None
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    if created is None or (now-created).total_seconds() >= settings.backup_interval_hours*3600:
        create_backup(db, settings.backup_directory, settings.backup_keep)
        return True
    return False
