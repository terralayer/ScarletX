from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from .media_library import VIDEO_EXTENSIONS, _match_local_scene, index_media_file_by_id, quick_fingerprint
from .models import History, MediaFile, MediaProbe, RootFolder, Scene, UnmatchedMediaFile, utcnow

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover - optional runtime fallback
    FileSystemEventHandler = object  # type: ignore[assignment]
    Observer = None  # type: ignore[assignment]


def _normalized(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _index_changed_path(session_factory, raw_path: str) -> None:
    path = Path(raw_path).expanduser()
    if path.suffix.casefold() not in VIDEO_EXTENSIONS or not path.exists() or not path.is_file():
        return
    absolute = _normalized(path)
    media_id: int | None = None
    with session_factory() as db:
        media = db.scalar(select(MediaFile).where(MediaFile.path == absolute).limit(1))
        if media is None:
            # Older rows may retain a non-resolved spelling of the same path.
            for candidate in db.scalars(select(MediaFile).where(MediaFile.path.like(f"%{path.name}"))).all():
                if _normalized(candidate.path) == absolute:
                    media = candidate
                    break
        if media is None:
            scenes = db.scalars(select(Scene).where(Scene.content_type == "scene")).all()
            scene = _match_local_scene(path, scenes)
            if scene is None:
                unmatched = db.scalar(select(UnmatchedMediaFile).where(UnmatchedMediaFile.path == absolute).limit(1))
                if unmatched is None:
                    unmatched = UnmatchedMediaFile(path=absolute, display_name=path.stem)
                    db.add(unmatched)
                stat = path.stat()
                unmatched.size_bytes = stat.st_size
                unmatched.fingerprint = quick_fingerprint(path)
                unmatched.missing = False
                unmatched.last_seen_at = utcnow()
                db.commit()
                return
            media = MediaFile(scene_id=scene.id, path=absolute, size_bytes=path.stat().st_size, quality=None, release_title=path.stem)
            db.add(media)
            old_unmatched = db.scalar(select(UnmatchedMediaFile).where(UnmatchedMediaFile.path == absolute).limit(1))
            if old_unmatched is not None:
                db.delete(old_unmatched)
            db.flush()
            media_id = media.id
            db.add(History(event_type="media_discovered", scene_id=scene.id, message=f"Detected new media file {path.name}"))
        else:
            media.path = absolute
            media.size_bytes = path.stat().st_size
            media_id = media.id
        db.commit()
    if media_id is not None:
        index_media_file_by_id(session_factory, media_id, generate_art=True)


def _mark_missing_path(session_factory, raw_path: str) -> None:
    absolute = _normalized(raw_path)
    with session_factory() as db:
        media = db.scalar(select(MediaFile).where(MediaFile.path == absolute).limit(1))
        if media is not None:
            probe = db.get(MediaProbe, media.id)
            if probe is None:
                probe = MediaProbe(media_file_id=media.id)
                db.add(probe)
            probe.missing = True
            probe.scanned_at = utcnow()
        unmatched = db.scalar(select(UnmatchedMediaFile).where(UnmatchedMediaFile.path == absolute).limit(1))
        if unmatched is not None:
            unmatched.missing = True
            unmatched.last_seen_at = utcnow()
        db.commit()


class _Handler(FileSystemEventHandler):
    def __init__(self, submit: Callable[[str, str], None]):
        super().__init__()
        self.submit = submit

    def _emit(self, kind: str, path: str) -> None:
        if Path(path).suffix.casefold() in VIDEO_EXTENSIONS:
            self.submit(kind, path)

    def on_created(self, event):
        if not event.is_directory:
            self._emit("changed", event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._emit("changed", event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._emit("deleted", event.src_path)
            self._emit("changed", event.dest_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._emit("deleted", event.src_path)


async def media_watch_loop(session_factory, refresh_seconds: float = 30.0) -> None:
    """Watch configured media roots and index changes without full rescans."""
    if Observer is None:
        # watchdog is optional for source-tree use; packaged installs include it.
        while True:
            await asyncio.sleep(3600)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=8192)
    observer = None
    watched: tuple[str, ...] = ()

    def submit(kind: str, path: str) -> None:
        def put() -> None:
            try:
                queue.put_nowait((kind, path))
            except asyncio.QueueFull:
                pass
        loop.call_soon_threadsafe(put)

    async def rebuild_if_needed() -> None:
        nonlocal observer, watched
        with session_factory() as db:
            roots = tuple(sorted({_normalized(x.path) for x in db.scalars(select(RootFolder).where(RootFolder.content_type == "scene")).all() if Path(x.path).expanduser().is_dir()}))
        if roots == watched:
            return
        if observer is not None:
            observer.stop()
            await asyncio.to_thread(observer.join, 5)
        observer = Observer()
        handler = _Handler(submit)
        for root in roots:
            observer.schedule(handler, root, recursive=True)
        if roots:
            observer.start()
        watched = roots

    try:
        await rebuild_if_needed()
        next_refresh = loop.time() + refresh_seconds
        pending: dict[str, str] = {}
        while True:
            timeout = max(0.1, min(1.0, next_refresh - loop.time()))
            try:
                kind, path = await asyncio.wait_for(queue.get(), timeout=timeout)
                pending[_normalized(path)] = kind
            except asyncio.TimeoutError:
                pass
            if loop.time() >= next_refresh:
                await rebuild_if_needed()
                next_refresh = loop.time() + refresh_seconds
            if not pending:
                continue
            # Coalesce bursty create/write/rename events and wait for a copy to settle.
            await asyncio.sleep(0.75)
            batch, pending = pending, {}
            for path, kind in batch.items():
                if kind == "deleted":
                    await asyncio.to_thread(_mark_missing_path, session_factory, path)
                    continue
                p = Path(path)
                try:
                    first = p.stat().st_size
                    await asyncio.sleep(0.35)
                    if not p.exists() or p.stat().st_size != first:
                        pending[path] = "changed"
                        continue
                except OSError:
                    continue
                await asyncio.to_thread(_index_changed_path, session_factory, path)
    finally:
        if observer is not None:
            observer.stop()
            await asyncio.to_thread(observer.join, 5)
