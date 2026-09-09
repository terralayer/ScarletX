from __future__ import annotations

import hashlib
import os
import shutil
from collections import defaultdict
from functools import wraps
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import History, MediaFile, MediaProbe, PlaybackState

GENERATED_ROOT = Path(os.getenv("SCARLETX_GENERATED_DIR", "./generated")).expanduser()
_HASH_CHUNK = 4 * 1024 * 1024


def _quick_fingerprint(path: Path, chunk_size: int = 1024 * 1024) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(chunk_size))
        if stat.st_size > chunk_size:
            handle.seek(max(0, stat.st_size - chunk_size))
            digest.update(handle.read(chunk_size))
    return digest.hexdigest()


def full_sha256(path: Path, chunk_size: int = _HASH_CHUNK) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_path(media: MediaFile) -> Path | None:
    path = Path(media.path).expanduser()
    try:
        return path if path.is_file() else None
    except OSError:
        return None


def _remove_duplicate_record(db: Session, duplicate: MediaFile, canonical: MediaFile) -> bool:
    duplicate_path = _existing_path(duplicate)
    canonical_path = _existing_path(canonical)
    if duplicate_path is None or canonical_path is None:
        return False

    try:
        same_path = duplicate_path.resolve() == canonical_path.resolve()
    except OSError:
        same_path = str(duplicate_path) == str(canonical_path)

    if not same_path:
        try:
            duplicate_path.unlink()
        except OSError as exc:
            db.add(
                History(
                    event_type="duplicate_remove_failed",
                    scene_id=duplicate.scene_id,
                    message=f"Could not remove exact duplicate {duplicate.path}: {exc}",
                )
            )
            return False

    probe = db.get(MediaProbe, duplicate.id)
    if probe is not None:
        db.delete(probe)
    playback = db.get(PlaybackState, duplicate.id)
    if playback is not None:
        db.delete(playback)
    shutil.rmtree(GENERATED_ROOT / "media" / str(duplicate.id), ignore_errors=True)
    db.add(
        History(
            event_type="duplicate_removed",
            scene_id=duplicate.scene_id,
            message=f"Removed exact duplicate {duplicate.path}; kept {canonical.path}",
        )
    )
    db.delete(duplicate)
    db.flush()
    return True


def _verified_duplicate_groups(rows: list[MediaFile]) -> list[list[MediaFile]]:
    """Find byte-identical candidates using cheap fingerprint then full SHA-256."""
    by_size: dict[int, list[MediaFile]] = defaultdict(list)
    for media in rows:
        path = _existing_path(media)
        if path is None:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        media.size_bytes = size
        by_size[size].append(media)

    exact_groups: list[list[MediaFile]] = []
    for size_rows in by_size.values():
        if len(size_rows) < 2:
            continue
        by_quick: dict[str, list[MediaFile]] = defaultdict(list)
        for media in size_rows:
            path = _existing_path(media)
            if path is None:
                continue
            try:
                by_quick[_quick_fingerprint(path)].append(media)
            except OSError:
                continue
        for quick_rows in by_quick.values():
            if len(quick_rows) < 2:
                continue
            by_full: dict[str, list[MediaFile]] = defaultdict(list)
            for media in quick_rows:
                path = _existing_path(media)
                if path is None:
                    continue
                try:
                    by_full[full_sha256(path)].append(media)
                except OSError:
                    continue
            exact_groups.extend(group for group in by_full.values() if len(group) > 1)
    return exact_groups


def remove_exact_duplicates(db: Session, *, scene_id: int | None = None) -> dict[str, int]:
    """Delete only verified byte-identical duplicate files belonging to the same scene."""
    stmt = select(MediaFile).order_by(MediaFile.scene_id.asc(), MediaFile.id.asc())
    if scene_id is not None:
        stmt = stmt.where(MediaFile.scene_id == scene_id)
    rows = db.scalars(stmt).all()
    by_scene: dict[int, list[MediaFile]] = defaultdict(list)
    for media in rows:
        by_scene[int(media.scene_id)].append(media)

    removed = 0
    reclaimed = 0
    for scene_rows in by_scene.values():
        for group in _verified_duplicate_groups(scene_rows):
            ordered = sorted(group, key=lambda media: media.id)
            canonical = ordered[0]
            for duplicate in ordered[1:]:
                path = _existing_path(duplicate)
                size = path.stat().st_size if path is not None else 0
                if _remove_duplicate_record(db, duplicate, canonical):
                    removed += 1
                    reclaimed += int(size)
    return {"removed": removed, "bytes_reclaimed": reclaimed}


def deduplicate_imported_media(db: Session, media: MediaFile) -> MediaFile:
    """Collapse a newly imported exact duplicate back to the canonical media row."""
    rows = db.scalars(
        select(MediaFile)
        .where(MediaFile.scene_id == media.scene_id)
        .order_by(MediaFile.id.asc())
    ).all()
    if len(rows) < 2:
        return media

    for group in _verified_duplicate_groups(rows):
        if all(candidate.id != media.id for candidate in group):
            continue
        canonical = min(group, key=lambda candidate: candidate.id)
        if canonical.id == media.id:
            return media
        if _remove_duplicate_record(db, media, canonical):
            return canonical
    return media


def install_runtime_dedup(legacy_application) -> None:
    """Install dedup at the legacy import/scan boundaries during app composition."""
    from . import library_management, media_library

    original_import = library_management.import_specific_media_file
    if not getattr(original_import, "_scarletx_exact_dedup", False):
        @wraps(original_import)
        def import_with_exact_dedup(*args, **kwargs):
            db = args[0] if args else kwargs["db"]
            media = original_import(*args, **kwargs)
            return deduplicate_imported_media(db, media)

        import_with_exact_dedup._scarletx_exact_dedup = True
        library_management.import_specific_media_file = import_with_exact_dedup
        legacy_application.import_specific_media_file = import_with_exact_dedup

    original_scan = media_library.scan_library
    if not getattr(original_scan, "_scarletx_exact_dedup", False):
        @wraps(original_scan)
        def scan_with_exact_dedup(session_factory, *args, **kwargs):
            stats = original_scan(session_factory, *args, **kwargs)
            with session_factory() as db:
                cleanup = remove_exact_duplicates(db)
                stats["duplicates_removed"] = cleanup["removed"]
                stats["duplicate_bytes_reclaimed"] = cleanup["bytes_reclaimed"]
                db.commit()
            return stats

        scan_with_exact_dedup._scarletx_exact_dedup = True
        media_library.scan_library = scan_with_exact_dedup
        legacy_application.scan_library = scan_with_exact_dedup
