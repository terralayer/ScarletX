from __future__ import annotations

import concurrent.futures
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .library_match import build_scene_match_index, match_local_scene
from .library_scanner import load_states, normalized_path, record_success, reconcile_missing, scandir_videos, unchanged
from .status_console import emit_status
from .models import (
    BackgroundJob,
    History,
    MediaFile,
    MediaProbe,
    PlaybackState,
    RootFolder,
    Scene,
    UnmatchedMediaFile,
    utcnow,
)

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".ts", ".m2ts", ".mpg", ".mpeg"}
GENERATED_ROOT = Path(os.getenv("SCARLETX_GENERATED_DIR", "./generated")).expanduser()


class MediaLibraryError(RuntimeError):
    pass


def tool_status() -> dict[str, bool]:
    return {
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
    }


def _run(args: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, capture_output=True, text=True, check=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaLibraryError(f"Required media tool is not installed: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaLibraryError(f"Media tool timed out: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise MediaLibraryError(detail[-1500:] or f"{args[0]} failed") from exc


def probe_path(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise MediaLibraryError(f"Media file does not exist: {path}")
    result = _run([
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)
    ], timeout=60)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaLibraryError("ffprobe returned invalid JSON") from exc
    streams = payload.get("streams") or []
    video = next((x for x in streams if x.get("codec_type") == "video"), {})
    audio = next((x for x in streams if x.get("codec_type") == "audio"), {})
    fmt = payload.get("format") or {}
    duration = fmt.get("duration") or video.get("duration")
    bitrate = fmt.get("bit_rate") or video.get("bit_rate")
    try:
        duration_value = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration_value = None
    try:
        bitrate_value = int(float(bitrate)) if bitrate is not None else None
    except (TypeError, ValueError):
        bitrate_value = None
    return {
        "duration_seconds": duration_value,
        "width": int(video.get("width")) if video.get("width") else None,
        "height": int(video.get("height")) if video.get("height") else None,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "container": fmt.get("format_name"),
        "bitrate_bps": bitrate_value,
    }


def quick_fingerprint(path: Path, chunk_size: int = 1024 * 1024) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(chunk_size))
        if stat.st_size > chunk_size:
            handle.seek(max(0, stat.st_size - chunk_size))
            digest.update(handle.read(chunk_size))
    return digest.hexdigest()


def _asset_dir(media_id: int) -> Path:
    root = GENERATED_ROOT / "media" / str(media_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def generate_screengrab(media_id: int, path: Path, duration_seconds: float | None = None, *, force: bool = False) -> tuple[str, str]:
    root = _asset_dir(media_id)
    screengrab = root / "screengrab.jpg"
    thumbnail = root / "thumbnail.jpg"
    if force or not screengrab.exists():
        seek = max(0.0, min((duration_seconds or 0) * 0.22, 300.0)) if duration_seconds else 30.0
        args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        if seek:
            args += ["-ss", f"{seek:.3f}"]
        args += ["-i", str(path), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(screengrab)]
        _run(args, timeout=120)
    if screengrab.exists() and (force or not thumbnail.exists()):
        try:
            with Image.open(screengrab) as image:
                image.thumbnail((420, 260))
                image.convert("RGB").save(thumbnail, "JPEG", quality=84, optimize=True)
        except Exception:
            shutil.copy2(screengrab, thumbnail)
    return str(screengrab), str(thumbnail)


def generate_preview(media_id: int, path: Path, duration_seconds: float | None = None, *, force: bool = False) -> str:
    root = _asset_dir(media_id)
    preview = root / "preview.mp4"
    if preview.exists() and not force:
        return str(preview)
    start = max(0.0, min((duration_seconds or 0) * 0.25, 600.0)) if duration_seconds else 20.0
    _run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(path), "-t", "8",
        "-vf", "scale='min(854,iw)':-2", "-an", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "28", "-movflags", "+faststart", str(preview),
    ], timeout=180)
    return str(preview)


def index_media_file(db: Session, media: MediaFile, *, generate_art: bool = True) -> MediaProbe:
    path = Path(media.path).expanduser()
    probe = db.get(MediaProbe, media.id)
    if probe is None:
        probe = MediaProbe(media_file_id=media.id)
        db.add(probe)
    if not path.exists() or not path.is_file():
        probe.missing = True
        probe.scanned_at = utcnow()
        db.flush()
        return probe
    stat = path.stat()
    unchanged = bool(probe.file_mtime == stat.st_mtime and probe.size_bytes == stat.st_size and probe.duration_seconds is not None)
    if not unchanged:
        details = probe_path(path)
        probe.duration_seconds = details["duration_seconds"]
        probe.width = details["width"]
        probe.height = details["height"]
        probe.video_codec = details["video_codec"]
        probe.audio_codec = details["audio_codec"]
        probe.container = details["container"]
        probe.bitrate_bps = details["bitrate_bps"]
        probe.fingerprint = quick_fingerprint(path)
        probe.file_mtime = stat.st_mtime
        probe.size_bytes = stat.st_size
    probe.missing = False
    probe.scanned_at = utcnow()
    if generate_art and tool_status()["ffmpeg"]:
        try:
            screenshot, thumb = generate_screengrab(media.id, path, probe.duration_seconds)
            probe.screengrab_path = screenshot
            probe.thumbnail_path = thumb
        except MediaLibraryError:
            pass
    db.flush()
    return probe


def index_media_file_by_id(session_factory, media_id: int, *, generate_art: bool = True) -> bool:
    with session_factory() as db:
        media = db.get(MediaFile, media_id)
        if media is None:
            return False
        try:
            index_media_file(db, media, generate_art=generate_art)
            db.commit()
            return True
        except Exception as exc:
            db.add(History(event_type="media_probe_failed", scene_id=media.scene_id, message=f"Media probe failed for {media.path}: {exc}"))
            db.commit()
            return False


def _norm(value: str) -> str:
    value = Path(value).stem.casefold()
    value = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", value)
    # Apostrophes commonly disappear from release filenames. Removing them
    # before separator normalization makes "Don't" and "Dont" equivalent.
    value = re.sub(r"['’ʼ]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _match_local_scene(path: Path, scenes: list[Scene]) -> Scene | None:
    stem = _norm(path.name)
    ranked: list[tuple[int, Scene]] = []
    for scene in scenes:
        title = _norm(scene.title)
        if len(title) < 4:
            continue
        if stem == title:
            ranked.append((10000 + len(title), scene))
        elif title in stem:
            ranked.append((len(title), scene))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]


def _video_paths(root: Path):
    for path, _stat in scandir_videos((root,), VIDEO_EXTENSIONS):
        yield path


def scan_library(
    session_factory,
    job_id: int | None = None,
    *,
    directories: list[str | Path] | None = None,
) -> dict[str, Any]:
    stats = {"files": 0, "indexed": 0, "skipped": 0, "matched": 0, "unmatched": 0, "missing": 0, "errors": 0}
    emit_status("Library Scan", "ACTIVE", "scanning configured scene roots", severity="active")
    to_index: list[int] = []
    pending_states: dict[int, tuple[Path, os.stat_result]] = {}
    with session_factory() as db:
        job = db.get(BackgroundJob, job_id) if job_id else None
        if job:
            job.status = "running"
            db.commit()
        roots = db.scalars(select(RootFolder).where(RootFolder.content_type == "scene")).all()
        root_paths = (
            [Path(row.path).expanduser() for row in roots]
            if directories is None
            else [Path(path).expanduser() for path in directories]
        )
        scan_states = load_states(db, root_paths)
        failed_directories: set[Path] = set()
        scope_prefixes = tuple(normalized_path(path).rstrip(os.sep) + os.sep for path in root_paths)

        def in_scope(path: str) -> bool:
            return normalized_path(path).startswith(scope_prefixes)
        scenes = db.scalars(select(Scene).where(Scene.content_type == "scene")).all()
        scene_match_index = build_scene_match_index(scenes)
        probe_map = {probe.media_file_id: probe for probe in db.scalars(select(MediaProbe)).all()}
        known = {str(Path(x.path).expanduser().resolve(strict=False)): x for x in db.scalars(select(MediaFile)).all()}
        seen: set[str] = set()
        unmatched_known = {str(Path(x.path).expanduser().resolve(strict=False)): x for x in db.scalars(select(UnmatchedMediaFile)).all()}
        try:
            for root in root_paths:
                for path, stat in scandir_videos(
                    (root,), VIDEO_EXTENSIONS,
                    on_error=lambda directory, _exc: failed_directories.add(directory),
                ):
                    stats["files"] += 1
                    key = normalized_path(path)
                    seen.add(key)
                    if unchanged(scan_states.get(key), stat, path=path):
                        stats["skipped"] += 1
                        continue
                    media = known.get(key)
                    if media is None:
                        scene = match_local_scene(path, scene_match_index)
                        if scene is not None:
                            media = MediaFile(scene_id=scene.id, path=key, size_bytes=stat.st_size, quality=None, release_title=path.stem)
                            db.add(media); db.flush(); known[key] = media
                            old_unmatched = unmatched_known.get(key)
                            if old_unmatched is not None:
                                db.delete(old_unmatched)
                            stats["matched"] += 1
                        else:
                            item = unmatched_known.get(key)
                            if item is None:
                                item = UnmatchedMediaFile(path=key, display_name=path.stem)
                                db.add(item); db.flush(); unmatched_known[key] = item
                            # Reaching this branch means persistent size/mtime_ns
                            # identity changed (or no state exists), so refresh the
                            # fingerprint even when the byte count is unchanged.
                            item.fingerprint = quick_fingerprint(path)
                            item.size_bytes = stat.st_size
                            item.missing = False
                            item.last_seen_at = utcnow()
                            record_success(db, path, stat)
                            stats["unmatched"] += 1
                            continue
                    probe = probe_map.get(media.id)
                    if probe and probe.file_mtime == stat.st_mtime and probe.size_bytes == stat.st_size and probe.duration_seconds is not None and not probe.missing:
                        stats["skipped"] += 1
                    else:
                        to_index.append(media.id)
                        pending_states[media.id] = (path, stat)
                    if media.id not in pending_states:
                        record_success(db, path, stat)
                    if stats["files"] % 20 == 0:
                        db.commit()
            # Mark DB media that disappeared from configured roots as missing.
            for key, media in known.items():
                if key in seen or not in_scope(key):
                    continue
                probe = probe_map.get(media.id)
                if probe is None:
                    probe = MediaProbe(media_file_id=media.id)
                    db.add(probe)
                    probe_map[media.id] = probe
                if not Path(media.path).exists():
                    probe.missing = True
                    probe.scanned_at = utcnow()
                    stats["missing"] += 1
            for key, item in unmatched_known.items():
                if in_scope(key) and key not in seen and not Path(item.path).exists():
                    item.missing = True
            reconcile_missing(db, scan_states, seen, failed_directories)
            stats["errors"] += len(failed_directories)
            stats["failed_directories"] = [str(path) for path in sorted(failed_directories)]
            db.commit()

            # Probe changed/new files with separate DB sessions so ffprobe and
            # thumbnail generation can run concurrently without sharing a Session.
            if to_index:
                workers = min(4, max(1, (os.cpu_count() or 2) // 2), len(to_index))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scarletx-media") as pool:
                    futures = {
                        pool.submit(index_media_file_by_id, session_factory, media_id, generate_art=True): media_id
                        for media_id in to_index
                    }
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            media_id = futures[future]
                            if future.result():
                                stats["indexed"] += 1
                                path, stat = pending_states[media_id]
                                record_success(db, path, stat)
                            else:
                                stats["errors"] += 1
                        except Exception:
                            stats["errors"] += 1

            db.add(History(event_type="library_scan", scene_id=None, message=f"Library scan: {stats['files']} files, {stats['indexed']} indexed, {stats['skipped']} unchanged, {stats['unmatched']} unmatched, {stats['missing']} missing"))
            if job:
                job.status = "completed"
                job.payload = json.dumps(stats)
                job.finished_at = utcnow()
            db.commit()
        except Exception as exc:
            emit_status("Library Scan", "FAILED", exc.__class__.__name__, severity="error")
            if job:
                job.status = "failed"
                job.error = str(exc)[:2000]
                job.finished_at = utcnow()
            db.commit()
            raise
    emit_status(
        "Library Scan",
        "COMPLETED",
        f"{stats['files']} files | {stats['indexed']} indexed | {stats['unmatched']} unmatched | {stats['errors']} errors",
        severity="ok" if stats["errors"] == 0 else "warning",
    )
    return stats


def library_stats(db: Session) -> dict[str, Any]:
    files = db.scalar(select(func.count(MediaFile.id))) or 0
    missing = db.scalar(select(func.count(MediaProbe.media_file_id)).where(MediaProbe.missing.is_(True))) or 0
    unmatched = db.scalar(select(func.count(UnmatchedMediaFile.id)).where(UnmatchedMediaFile.missing.is_(False))) or 0
    total_bytes = db.scalar(select(func.sum(MediaFile.size_bytes))) or 0
    fingerprints = db.execute(
        select(MediaProbe.fingerprint, func.count(MediaProbe.media_file_id))
        .where(MediaProbe.fingerprint.is_not(None), MediaProbe.missing.is_(False))
        .group_by(MediaProbe.fingerprint)
        .having(func.count(MediaProbe.media_file_id) > 1)
    ).all()
    duplicate_groups = len(fingerprints)
    return {
        "files": int(files), "missing": int(missing), "unmatched": int(unmatched),
        "total_bytes": int(total_bytes), "duplicate_groups": duplicate_groups,
        "tools": tool_status(),
    }


def media_rows(db: Session, rows: list[MediaFile]) -> list[dict[str, Any]]:
    """Serialize a page of media with three bulk lookups instead of N+1 queries."""
    if not rows:
        return []
    media_ids = [x.id for x in rows]
    scene_ids = {x.scene_id for x in rows}
    scenes = {x.id: x for x in db.scalars(select(Scene).where(Scene.id.in_(scene_ids)).options(selectinload(Scene.studio))).all()}
    probes = {x.media_file_id: x for x in db.scalars(select(MediaProbe).where(MediaProbe.media_file_id.in_(media_ids))).all()}
    playbacks = {x.media_file_id: x for x in db.scalars(select(PlaybackState).where(PlaybackState.media_file_id.in_(media_ids))).all()}
    result = []
    for media in rows:
        scene = scenes.get(media.scene_id); probe = probes.get(media.id); playback = playbacks.get(media.id)
        result.append({
            "id": media.id, "scene_id": media.scene_id,
            "scene_title": scene.title if scene else media.release_title or Path(media.path).stem,
            "studio": scene.studio.name if scene and scene.studio else None,
            "path": media.path, "filename": Path(media.path).name, "size_bytes": media.size_bytes,
            "quality": media.quality, "release_title": media.release_title, "imported_at": media.imported_at,
            "missing": bool(probe.missing) if probe else not Path(media.path).exists(),
            "duration_seconds": probe.duration_seconds if probe else None, "width": probe.width if probe else None,
            "height": probe.height if probe else None, "video_codec": probe.video_codec if probe else None,
            "audio_codec": probe.audio_codec if probe else None, "container": probe.container if probe else None,
            "bitrate_bps": probe.bitrate_bps if probe else None, "fingerprint": probe.fingerprint if probe else None,
            "thumbnail_ready": bool(probe and probe.thumbnail_path and Path(probe.thumbnail_path).exists()),
            "screengrab_ready": bool(probe and probe.screengrab_path and Path(probe.screengrab_path).exists()),
            "preview_ready": bool(probe and probe.preview_path and Path(probe.preview_path).exists()),
            "position_seconds": playback.position_seconds if playback else 0.0,
            "play_count": playback.play_count if playback else 0, "favorite": bool(playback.favorite) if playback else False,
            "last_played_at": playback.last_played_at if playback else None,
        })
    return result


def media_row(db: Session, media: MediaFile) -> dict[str, Any]:
    scene = db.get(Scene, media.scene_id)
    probe = db.get(MediaProbe, media.id)
    playback = db.get(PlaybackState, media.id)
    return {
        "id": media.id,
        "scene_id": media.scene_id,
        "scene_title": scene.title if scene else media.release_title or Path(media.path).stem,
        "studio": scene.studio.name if scene and scene.studio else None,
        "path": media.path,
        "filename": Path(media.path).name,
        "size_bytes": media.size_bytes,
        "quality": media.quality,
        "release_title": media.release_title,
        "imported_at": media.imported_at,
        "missing": bool(probe.missing) if probe else not Path(media.path).exists(),
        "duration_seconds": probe.duration_seconds if probe else None,
        "width": probe.width if probe else None,
        "height": probe.height if probe else None,
        "video_codec": probe.video_codec if probe else None,
        "audio_codec": probe.audio_codec if probe else None,
        "container": probe.container if probe else None,
        "bitrate_bps": probe.bitrate_bps if probe else None,
        "fingerprint": probe.fingerprint if probe else None,
        "thumbnail_ready": bool(probe and probe.thumbnail_path and Path(probe.thumbnail_path).exists()),
        "screengrab_ready": bool(probe and probe.screengrab_path and Path(probe.screengrab_path).exists()),
        "preview_ready": bool(probe and probe.preview_path and Path(probe.preview_path).exists()),
        "position_seconds": playback.position_seconds if playback else 0.0,
        "play_count": playback.play_count if playback else 0,
        "favorite": bool(playback.favorite) if playback else False,
        "last_played_at": playback.last_played_at if playback else None,
    }


def duplicate_rows(db: Session) -> list[dict[str, Any]]:
    groups = db.execute(
        select(MediaProbe.fingerprint)
        .where(MediaProbe.fingerprint.is_not(None), MediaProbe.missing.is_(False))
        .group_by(MediaProbe.fingerprint)
        .having(func.count(MediaProbe.media_file_id) > 1)
    ).scalars().all()
    if not groups:
        return []
    probes = db.scalars(select(MediaProbe).where(MediaProbe.fingerprint.in_(groups), MediaProbe.missing.is_(False))).all()
    fingerprint_by_media = {probe.media_file_id: probe.fingerprint for probe in probes}
    files = db.scalars(select(MediaFile).where(MediaFile.id.in_(fingerprint_by_media))).all()
    rows_by_media = {row["id"]: row for row in media_rows(db, files)}
    files_by_fingerprint: dict[str, list[dict[str, Any]]] = {fingerprint: [] for fingerprint in groups}
    for media_id, fingerprint in fingerprint_by_media.items():
        row = rows_by_media.get(media_id)
        if row is not None and fingerprint is not None:
            files_by_fingerprint[fingerprint].append(row)
    return [{"fingerprint": fingerprint, "files": files_by_fingerprint[fingerprint]} for fingerprint in groups]


def update_playback(db: Session, media_id: int, *, position_seconds: float | None = None, favorite: bool | None = None, played: bool = False) -> PlaybackState:
    state = db.get(PlaybackState, media_id)
    if state is None:
        state = PlaybackState(media_file_id=media_id, position_seconds=0.0, play_count=0, favorite=False)
        db.add(state)
    if position_seconds is not None:
        state.position_seconds = max(0.0, float(position_seconds))
    if favorite is not None:
        state.favorite = bool(favorite)
    if played:
        state.play_count = int(state.play_count or 0) + 1
        state.last_played_at = datetime.now(UTC)
    state.updated_at = datetime.now(UTC)
    db.flush()
    return state


def asset_for(db: Session, media_id: int, kind: str) -> Path:
    media = db.get(MediaFile, media_id)
    if media is None:
        raise MediaLibraryError("Media file not found")
    probe = db.get(MediaProbe, media_id)
    path = Path(media.path)
    if not path.exists():
        raise MediaLibraryError("Media file is missing")
    if probe is None or probe.missing:
        probe = index_media_file(db, media, generate_art=True)
    if kind == "preview":
        preview = generate_preview(media.id, path, probe.duration_seconds)
        probe.preview_path = preview
        db.flush()
        return Path(preview)
    if kind in {"thumbnail", "screengrab"}:
        screenshot, thumb = generate_screengrab(media.id, path, probe.duration_seconds)
        probe.screengrab_path = screenshot
        probe.thumbnail_path = thumb
        db.flush()
        return Path(thumb if kind == "thumbnail" else screenshot)
    raise MediaLibraryError("Unknown media asset")


def media_type_for(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
