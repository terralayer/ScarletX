from __future__ import annotations

import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Iterable, Iterator

from sqlalchemy import delete, select

from .models import FileScanState, utcnow
from .recent_imports import FileIdentity, recent_imports


def normalized_path(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


class DirtyDirectoryQueue:
    """Thread-safe, bounded and coalescing directory work queue."""

    def __init__(self, max_entries: int = 8192):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._directories: OrderedDict[str, Path] = OrderedDict()
        self._overflowed = False
        self._lock = threading.Lock()

    def mark(self, path: str | Path, *, is_directory: bool = False) -> None:
        value = Path(path).expanduser()
        directory = value if is_directory else value.parent
        key = normalized_path(directory)
        with self._lock:
            if key in self._directories:
                return
            if len(self._directories) >= self.max_entries:
                self._overflowed = True
                return
            self._directories[key] = Path(key)

    def drain(self, limit: int) -> list[Path]:
        if limit < 1:
            return []
        with self._lock:
            keys = list(self._directories)[:limit]
            return [self._directories.pop(key) for key in keys]

    def overflow(self) -> bool:
        with self._lock:
            value = self._overflowed
            self._overflowed = False
            return value

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._directories)


def scandir_videos(
    directories: Iterable[str | Path],
    extensions: set[str],
    *,
    on_error: Callable[[Path, OSError], None] | None = None,
) -> Iterator[tuple[Path, os.stat_result]]:
    """Recursively yield videos while isolating failures to individual directories."""

    pending = [Path(item).expanduser() for item in directories]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.casefold() in extensions:
                            yield Path(entry.path), entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        if on_error is not None:
                            on_error(Path(entry.path).parent, exc)
                        continue
        except OSError as exc:
            if on_error is not None:
                on_error(directory, exc)
            continue


def unchanged(
    state: FileScanState | None,
    stat: os.stat_result,
    *,
    path: str | Path | None = None,
) -> bool:
    if state and state.size_bytes == stat.st_size and state.mtime_ns == stat.st_mtime_ns:
        return True
    return bool(path is not None and recent_imports.contains(FileIdentity.from_stat(path, stat)))


def load_states(db, directories: Iterable[str | Path]) -> dict[str, FileScanState]:
    prefixes = tuple(normalized_path(item).rstrip(os.sep) + os.sep for item in directories)
    if not prefixes:
        return {}
    return {
        row.path: row
        for row in db.scalars(select(FileScanState)).all()
        if row.path.startswith(prefixes)
    }


def record_success(db, path: str | Path, stat: os.stat_result) -> None:
    key = normalized_path(path)
    state = db.get(FileScanState, key)
    if state is None:
        state = FileScanState(path=key, size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
        db.add(state)
    else:
        state.size_bytes = stat.st_size
        state.mtime_ns = stat.st_mtime_ns
        state.scanned_at = utcnow()


def reconcile_missing(
    db,
    states: dict[str, FileScanState],
    seen: set[str],
    failed_directories: Iterable[str | Path] = (),
) -> set[str]:
    failed_prefixes = tuple(
        normalized_path(item).rstrip(os.sep) + os.sep for item in failed_directories
    )
    missing = {
        path for path in set(states).difference(seen)
        if not path.startswith(failed_prefixes)
    }
    if missing:
        db.execute(delete(FileScanState).where(FileScanState.path.in_(missing)))
    return missing


def scan_directories(session_factory, directories, *, full: bool = False):
    """Scan explicit dirty scopes; ``full`` requests configured-root recovery."""
    from .media_library import scan_library

    return scan_library(session_factory, directories=None if full else directories)
