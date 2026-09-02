from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class FileIdentity:
    path: str
    size_bytes: int
    mtime_ns: int

    @classmethod
    def from_path(cls, path: str | Path) -> FileIdentity:
        value = Path(path).expanduser()
        stat = value.stat()
        return cls(
            path=str(value.resolve(strict=False)),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )

    @classmethod
    def from_stat(cls, path: str | Path, stat) -> FileIdentity:
        value = Path(path).expanduser()
        return cls(
            path=str(value.resolve(strict=False)),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )


class RecentImportRegistry:
    """Bounded process-local LRU for suppressing duplicate import events."""

    def __init__(
        self,
        max_entries: int = 2048,
        ttl_seconds: float = 300,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._entries: OrderedDict[FileIdentity, float] = OrderedDict()
        self._lock = threading.RLock()

    def register(self, identity: FileIdentity) -> None:
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._entries.pop(identity, None)
            self._entries[identity] = now
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def contains(self, identity: FileIdentity) -> bool:
        now = self._clock()
        with self._lock:
            self._prune(now)
            if identity not in self._entries:
                return False
            self._entries.move_to_end(identity)
            return True

    def _prune(self, now: float) -> None:
        expired = [
            identity
            for identity, registered_at in self._entries.items()
            if now - registered_at >= self.ttl_seconds
        ]
        for identity in expired:
            self._entries.pop(identity, None)


recent_imports = RecentImportRegistry()
