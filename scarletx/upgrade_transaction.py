from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from .models import History, MediaFile


def finalize_verified_upgrade(
    db: Session,
    *,
    new_media_id: int,
    previous_media_ids: list[int],
    verified: bool,
) -> int:
    """Retire prior scene media only after the replacement has been verified."""

    if not verified:
        return 0

    new_media = db.get(MediaFile, new_media_id)
    if new_media is None:
        return 0

    new_path = Path(new_media.path).expanduser().resolve(strict=False)
    retired = 0
    for media_id in dict.fromkeys(previous_media_ids):
        if media_id == new_media_id:
            continue
        previous = db.get(MediaFile, media_id)
        if previous is None or previous.scene_id != new_media.scene_id:
            continue

        previous_path = Path(previous.path).expanduser()
        previous_resolved = previous_path.resolve(strict=False)
        if previous_resolved == new_path:
            continue
        if previous_path.exists():
            if not previous_path.is_file():
                raise OSError(f"Previous media path is not a file: {previous_path}")
            previous_path.unlink()
        db.delete(previous)
        retired += 1

    if retired:
        db.add(
            History(
                event_type="media_upgraded",
                scene_id=new_media.scene_id,
                message=(
                    f"Verified upgrade replaced {retired} previous media file(s) "
                    f"with {Path(new_media.path).name}"
                )[:1000],
            )
        )
    db.flush()
    return retired


def rollback_upgrade_candidate(
    db: Session,
    *,
    new_media_id: int,
    reason: str,
) -> bool:
    """Remove a failed candidate while leaving all previous scene media untouched."""

    media = db.get(MediaFile, new_media_id)
    if media is None:
        return False

    candidate_path = Path(media.path).expanduser()
    scene_id = media.scene_id
    candidate_name = candidate_path.name
    if candidate_path.exists():
        if not candidate_path.is_file():
            raise OSError(f"Upgrade candidate path is not a file: {candidate_path}")
        candidate_path.unlink()
    db.delete(media)
    db.add(
        History(
            event_type="media_upgrade_rolled_back",
            scene_id=scene_id,
            message=f"Upgrade candidate rolled back: {candidate_name} | {reason}"[:1000],
        )
    )
    db.flush()
    return True
