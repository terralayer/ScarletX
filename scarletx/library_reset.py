from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .models import (
    FileScanState,
    History,
    IndexerFeedItem,
    LibraryItemConfig,
    MediaFile,
    MediaProbe,
    PlaybackState,
    Performer,
    ReleaseBlocklist,
    ScanPathDirectory,
    ScanPathIndex,
    Scene,
    Studio,
    Tag,
    TrackedDownload,
    UnmatchedMediaFile,
    UserTag,
    library_user_tag,
    scene_performer,
    scene_tag,
)


def _resolved_roots(root_paths: Iterable[str | Path]) -> tuple[Path, ...]:
    return tuple(Path(path).expanduser().resolve() for path in root_paths if str(path).strip())


def _delete_library_file(path: str, roots: tuple[Path, ...]) -> tuple[bool, bool]:
    """Delete a tracked file only when it is inside a configured scene root."""
    try:
        resolved = Path(path).expanduser().resolve()
        if not any(root != resolved and root in resolved.parents for root in roots):
            return False, True
        if not resolved.exists():
            return False, False
        if not resolved.is_file():
            return False, True
        resolved.unlink()
        return True, False
    except OSError:
        return False, True


def _delete_generated_assets(generated_root: str | Path | None, media_ids: Iterable[int]) -> None:
    if not generated_root:
        return
    media_root = Path(generated_root).expanduser().resolve() / "media"
    for media_id in media_ids:
        asset_dir = media_root / str(media_id)
        try:
            if media_root in asset_dir.parents:
                shutil.rmtree(asset_dir, ignore_errors=True)
        except OSError:
            continue


def reset_library(
    db: Session,
    *,
    root_paths: Iterable[str | Path],
    generated_root: str | Path | None = None,
) -> dict[str, int]:
    """Remove library content while retaining application and connection configuration."""
    roots = _resolved_roots(root_paths)
    scenes = db.scalars(select(Scene)).all()
    media = db.scalars(select(MediaFile)).all()
    performers = db.scalars(select(Performer)).all()
    studios = db.scalars(select(Studio)).all()
    scene_ids = [item.id for item in scenes]
    media_ids = [item.id for item in media]
    files_deleted = 0
    files_skipped = 0
    for item in media:
        deleted, skipped = _delete_library_file(item.path, roots)
        files_deleted += int(deleted)
        files_skipped += int(skipped)
    _delete_generated_assets(generated_root, media_ids)

    if scene_ids:
        db.execute(update(History).where(History.scene_id.in_(scene_ids)).values(scene_id=None))
        db.execute(update(IndexerFeedItem).where(IndexerFeedItem.scene_id.in_(scene_ids)).values(scene_id=None))
        db.execute(update(ReleaseBlocklist).where(ReleaseBlocklist.scene_id.in_(scene_ids)).values(scene_id=None))
        db.execute(update(TrackedDownload).where(TrackedDownload.scene_id.in_(scene_ids)).values(scene_id=None))
        db.execute(delete(library_user_tag).where(library_user_tag.c.scene_id.in_(scene_ids)))
        db.execute(delete(scene_performer).where(scene_performer.c.scene_id.in_(scene_ids)))
        db.execute(delete(scene_tag).where(scene_tag.c.scene_id.in_(scene_ids)))
        db.execute(delete(LibraryItemConfig).where(LibraryItemConfig.scene_id.in_(scene_ids)))

    if media_ids:
        db.execute(delete(MediaProbe).where(MediaProbe.media_file_id.in_(media_ids)))
        db.execute(delete(PlaybackState).where(PlaybackState.media_file_id.in_(media_ids)))
        db.execute(delete(MediaFile).where(MediaFile.id.in_(media_ids)))

    db.execute(delete(Scene))
    db.execute(delete(Performer))
    db.execute(delete(Studio))
    db.execute(delete(Tag))
    db.execute(delete(UserTag))
    db.execute(delete(UnmatchedMediaFile))
    db.execute(delete(FileScanState))
    db.execute(delete(ScanPathIndex))
    db.execute(delete(ScanPathDirectory))
    db.commit()
    return {
        "media_files": len(media),
        "files_deleted": files_deleted,
        "files_skipped": files_skipped,
        "scenes": len(scenes),
        "performers": len(performers),
        "studios": len(studios),
    }
