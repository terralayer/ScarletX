from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


def _same_device(source: Path, destination: Path) -> bool:
    source_dev = source.stat().st_dev
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_dev = destination.parent.stat().st_dev
    return source_dev == destination_dev


def _verify_copy(source: Path, copied: Path) -> None:
    source_stat = source.stat()
    copied_stat = copied.stat()
    if source_stat.st_size != copied_stat.st_size:
        raise IOError(
            f"Atomic publish verification failed: {copied_stat.st_size} != {source_stat.st_size}"
        )


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_file_atomic(source: Path, destination: Path, *, mode: str = "move") -> Path:
    """Publish a media file without exposing a partial final path."""

    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve(strict=False):
        return destination
    if not source.is_file():
        raise IOError(f"Atomic publish source is not a file: {source}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Atomic publish destination already exists: {destination}")

    if mode == "move" and _same_device(source, destination):
        os.replace(source, destination)
        _fsync_directory(destination.parent)
        return destination

    if mode not in {"move", "copy"}:
        raise ValueError(f"Unsupported atomic publish mode: {mode}")

    temporary = destination.with_name(
        f".{destination.name}.partial-{uuid.uuid4().hex}"
    )
    try:
        shutil.copy2(source, temporary)
        _verify_copy(source, temporary)
        _fsync_file(temporary)
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
        if mode == "move":
            source.unlink()
        return destination
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
