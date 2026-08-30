from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import engine
from .models import BackupRecord


class BackupError(RuntimeError):
    pass


def _backup_dir(directory: str) -> Path:
    path = Path(directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(db: Session, directory: str, keep: int = 14) -> BackupRecord:
    if engine.url.get_backend_name() != "sqlite":
        raise BackupError("Built-in ScarletX backup currently supports the local SQLite application database")
    source_name = engine.url.database
    if not source_name:
        raise BackupError("ScarletX SQLite database path is not available")
    source = Path(source_name)
    if not source.is_absolute():
        source = Path.cwd() / source
    target_dir = _backup_dir(directory)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = target_dir / f"scarletx-{timestamp}.db"
    try:
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
    except sqlite3.Error as exc:
        raise BackupError(f"ScarletX database backup failed: {exc}") from exc
    record = BackupRecord(path=str(target), size_bytes=target.stat().st_size)
    db.add(record)
    db.commit()
    db.refresh(record)
    rotate_backups(db, target_dir, keep)
    return record


def rotate_backups(db: Session, directory: Path, keep: int) -> None:
    keep = max(1, int(keep))
    records = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc())).all()
    for record in records[keep:]:
        path = Path(record.path)
        try:
            if path.exists() and path.parent.resolve() == directory.resolve():
                path.unlink()
        except OSError:
            continue
        db.delete(record)
    db.commit()


def list_backups(db: Session) -> list[dict]:
    rows = db.scalars(select(BackupRecord).order_by(BackupRecord.created_at.desc())).all()
    return [
        {
            "id": row.id,
            "path": row.path,
            "size_bytes": row.size_bytes,
            "created_at": row.created_at,
            "exists": Path(row.path).exists(),
        }
        for row in rows
    ]
