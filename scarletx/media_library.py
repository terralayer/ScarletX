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


def _image_asset(source: Path, target: Path, timestamp: float) -> None:
    _run(["ffmpeg", "-y", "-ss", f"{max(0.0, timestamp):.3f}", "-i", str(source), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", str(target)], timeout=180)


def _preview_asset(source: Path, target: Path, start: float, duration: float = 12.0) -> None:
    _run([
        "ffmpeg", "-y", "-ss", f"{max(0.0, start):.3f}", "-i", str(source), "-t", f"{duration:.1f}",
        "-vf", "scale='min(960,iw)':-2", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
        "-movflags", "+faststart", str(target),
    ], timeout=600)


def _write_thumbnail(source: Path, target: Path, timestamp: float) -> None:
    temp = target.with_name(f"{target.stem}.source.jpg")
    _image_asset(source, temp, timestamp)
    try:
        with Image.open(temp) as image:
            image.thumbnail((640, 360), Image.Resampling.LANCZOS)
            image.convert("RGB").save(target, format="JPEG", quality=86, optimize=True)
    finally:
        temp.unlink(missing_ok=True)


def _probe_media(path: Path) -> dict[str, Any]:
    return probe_path(path)


def _load_probe(db: Session, media_id: int) -> MediaProbe | None:
    return db.get(MediaProbe, media_id)


def index_media_file(db: Session, media: MediaFile, *, create_assets: bool = True) -> MediaProbe:
    path = Path(media.path)
    probe = _load_probe(db, media.id)
    if probe is None:
        probe = MediaProbe(media_file_id=media.id)
        db.add(probe)
    if not path.exists() or not path.is_file():
        probe.missing = True
        probe.scanned_at = utcnow()
        db.flush()
        return probe
    stat = path.stat()
    current_mtime = stat.st_mtime
    if (
        probe.scanned_at is not None
        and not probe.missing
        and probe.size_bytes == stat.st_size
        and probe.file_mtime is not None
        and abs(probe.file_mtime - current_mtime) < 0.001
        and probe.fingerprint
    ):
        return probe
    metadata = _probe_media(path)
    probe.duration_seconds = metadata.get("duration_seconds")
    probe.width = metadata.get("width")
    probe.height = metadata.get("height")
    probe.video_codec = metadata.get("video_codec")
    probe.audio_codec = metadata.get("audio_codec")
    probe.container = metadata.get("container")
    probe.bitrate_bps = metadata.get("bitrate_bps")
    probe.fingerprint = quick_fingerprint(path)
    probe.file_mtime = current_mtime
    probe.size_bytes = stat.st_size
    probe.missing = False
    probe.scanned_at = utcnow()
    media.size_bytes = stat.st_size
    if create_assets:
        duration = probe.duration_seconds or 0.0
        screenshot_at = max(1.0, min(duration * 0.25, max(duration - 1.0, 1.0))) if duration else 1.0
        asset_root = _asset_dir(media.id)
        screengrab = asset_root / "screengrab.jpg"
        thumbnail = asset_root / "thumbnail.jpg"
        try:
            _image_asset(path, screengrab, screenshot_at)
            probe.screengrab_path = str(screengrab)
        except MediaLibraryError:
            pass
        try:
            _write_thumbnail(path, thumbnail, screenshot_at)
            probe.thumbnail_path = str(thumbnail)
        except (MediaLibraryError, OSError):
            pass
    db.flush()
    return probe


def index_media_file_by_id(session_factory, media_id: int, *, create_assets: bool = True) -> None:
    with session_factory() as db:
        media = db.get(MediaFile, media_id)
        if media is None:
            return
        try:
            index_media_file(db, media, create_assets=create_assets)
            db.commit()
        except Exception:
            db.rollback()


def _media_rows_stmt():
    return select(MediaFile).options(selectinload(MediaFile.scene)).order_by(MediaFile.imported_at.desc(), MediaFile.id.desc())


def media_rows(db: Session, limit: int = 60, offset: int = 0) -> list[dict[str, Any]]:
    files = db.scalars(_media_rows_stmt().offset(offset).limit(limit)).all()
    if not files:
        return []
    probe_by_id = {x.media_file_id: x for x in db.scalars(select(MediaProbe).where(MediaProbe.media_file_id.in_([f.id for f in files]))).all()}
    state_by_id = {x.media_file_id: x for x in db.scalars(select(PlaybackState).where(PlaybackState.media_file_id.in_([f.id for f in files]))).all()}
    return [_media_row(f, probe_by_id.get(f.id), state_by_id.get(f.id)) for f in files]


def _media_row(media: MediaFile, probe: MediaProbe | None, state: PlaybackState | None) -> dict[str, Any]:
    scene = media.scene
    return {
        "id": media.id,
        "scene_id": media.scene_id,
        "scene_title": scene.title if scene else None,
        "studio": scene.studio.name if scene and scene.studio else None,
        "path": media.path,
        "size_bytes": media.size_bytes,
        "quality": media.quality,
        "release_title": media.release_title,
        "imported_at": media.imported_at,
        "duration_seconds": probe.duration_seconds if probe else None,
        "width": probe.width if probe else None,
        "height": probe.height if probe else None,
        "video_codec": probe.video_codec if probe else None,
        "audio_codec": probe.audio_codec if probe else None,
        "container": probe.container if probe else None,
        "bitrate_bps": probe.bitrate_bps if probe else None,
        "favorite": state.favorite if state else False,
        "position_seconds": state.position_seconds if state else 0.0,
        "play_count": state.play_count if state else 0,
        "missing": probe.missing if probe else not Path(media.path).exists(),
    }


def media_row(db: Session, media: MediaFile) -> dict[str, Any]:
    probe = db.get(MediaProbe, media.id)
    state = db.get(PlaybackState, media.id)
    return _media_row(media, probe, state)


def update_playback(db: Session, media_id: int, position_seconds: float | None = None, completed: bool = False, favorite: bool | None = None) -> PlaybackState:
    row = db.get(PlaybackState, media_id)
    if row is None:
        row = PlaybackState(media_file_id=media_id)
        db.add(row)
    if position_seconds is not None:
        row.position_seconds = max(0.0, position_seconds)
    if favorite is not None:
        row.favorite = favorite
    if completed:
        row.play_count += 1
        row.position_seconds = 0.0
    row.last_played_at = utcnow()
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def library_stats(db: Session) -> dict[str, Any]:
    media_files = db.scalar(select(func.count(MediaFile.id))) or 0
    missing = db.scalar(select(func.count(MediaProbe.media_file_id)).where(MediaProbe.missing.is_(True))) or 0
    unmatched = db.scalar(select(func.count(UnmatchedMediaFile.id)).where(UnmatchedMediaFile.missing.is_(False))) or 0
    total_bytes = db.scalar(select(func.coalesce(func.sum(MediaFile.size_bytes), 0))) or 0
    favorites = db.scalar(select(func.count(PlaybackState.media_file_id)).where(PlaybackState.favorite.is_(True))) or 0
    duration = db.scalar(select(func.coalesce(func.sum(MediaProbe.duration_seconds), 0.0))) or 0.0
    return {
        "files": media_files,
        "missing": missing,
        "unmatched": unmatched,
        "total_bytes": total_bytes,
        "favorites": favorites,
        "duration_seconds": duration,
    }


def duplicate_rows(db: Session) -> list[dict[str, Any]]:
    duplicates = db.execute(
        select(MediaProbe.fingerprint, func.count(MediaProbe.media_file_id))
        .where(MediaProbe.fingerprint.is_not(None), MediaProbe.missing.is_(False))
        .group_by(MediaProbe.fingerprint)
        .having(func.count(MediaProbe.media_file_id) > 1)
    ).all()
    rows = []
    for fingerprint, count in duplicates:
        files = db.scalars(
            select(MediaFile).join(MediaProbe, MediaProbe.media_file_id == MediaFile.id)
            .where(MediaProbe.fingerprint == fingerprint, MediaProbe.missing.is_(False))
            .order_by(MediaFile.imported_at.desc())
        ).all()
        rows.append({"fingerprint": fingerprint, "count": count, "files": [{"id": x.id, "scene_id": x.scene_id, "path": x.path, "size_bytes": x.size_bytes} for x in files]})
    return rows


def scan_library(session_factory) -> dict[str, Any]:
    summary = {"roots": 0, "files_seen": 0, "matched": 0, "unmatched": 0, "indexed": 0, "skipped_unchanged": 0, "errors": []}
    with session_factory() as db:
        roots = db.scalars(select(RootFolder).where(RootFolder.content_type == "scene").order_by(RootFolder.id)).all()
        scenes = db.scalars(select(Scene).options(selectinload(Scene.performers), selectinload(Scene.studio)).where(Scene.content_type == "scene")).unique().all()
        scene_index = build_scene_match_index(scenes)
        summary["roots"] = len(roots)
        root_paths = [Path(x.path).expanduser() for x in roots]
        prior_states = load_states(db.connection(), root_paths)
        observed_paths: set[str] = set()
        seen_media_ids: set[int] = set()
        summary_lock = __import__('threading').Lock()

        def inspect_file(path: Path) -> dict[str, Any]:
            try:
                stat = path.stat()
            except OSError as exc:
                return {"path": path, "error": str(exc)}
            key = normalized_path(path)
            with summary_lock:
                observed_paths.add(key)
                summary["files_seen"] += 1
            if unchanged(prior_states, path, stat):
                return {"path": path, "unchanged": True, "state": prior_states[key], "stat": stat}
            try:
                metadata = probe_path(path)
                fingerprint = quick_fingerprint(path)
            except (MediaLibraryError, OSError) as exc:
                return {"path": path, "error": str(exc), "stat": stat}
            return {"path": path, "metadata": metadata, "fingerprint": fingerprint, "stat": stat}

        tasks = []
        for root_path in root_paths:
            for path in scandir_videos(root_path, VIDEO_EXTENSIONS):
                tasks.append(path)
        workers = max(1, min(4, os.cpu_count() or 1))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            inspected = list(executor.map(inspect_file, tasks)) if tasks else []

        for item in inspected:
            path = item["path"]
            if item.get("unchanged"):
                state = item["state"]
                if state.media_file_id is not None:
                    seen_media_ids.add(state.media_file_id)
                summary["skipped_unchanged"] += 1
                continue
            if item.get("error"):
                summary["errors"].append({"path": str(path), "error": item["error"]})
                continue
            stat = item["stat"]
            metadata = item["metadata"]
            fingerprint = item["fingerprint"]
            match, score = match_local_scene(path, scenes, scene_index=scene_index)
            existing = db.scalar(select(MediaFile).where(MediaFile.path == str(path)))
            if match:
                if existing is None:
                    existing = MediaFile(scene_id=match.id, path=str(path), size_bytes=stat.st_size, quality=None, release_title=path.stem)
                    db.add(existing)
                    db.flush()
                elif existing.scene_id != match.id:
                    existing.scene_id = match.id
                probe = db.get(MediaProbe, existing.id)
                if probe is None:
                    probe = MediaProbe(media_file_id=existing.id)
                    db.add(probe)
                probe.duration_seconds = metadata.get("duration_seconds")
                probe.width = metadata.get("width")
                probe.height = metadata.get("height")
                probe.video_codec = metadata.get("video_codec")
                probe.audio_codec = metadata.get("audio_codec")
                probe.container = metadata.get("container")
                probe.bitrate_bps = metadata.get("bitrate_bps")
                probe.fingerprint = fingerprint
                probe.file_mtime = stat.st_mtime
                probe.size_bytes = stat.st_size
                probe.missing = False
                probe.scanned_at = utcnow()
                existing.size_bytes = stat.st_size
                seen_media_ids.add(existing.id)
                summary["matched"] += 1
                summary["indexed"] += 1
                record_success(db.connection(), path, stat, media_file_id=existing.id)
            else:
                row = db.scalar(select(UnmatchedMediaFile).where(UnmatchedMediaFile.path == str(path)))
                if row is None:
                    row = UnmatchedMediaFile(path=str(path), display_name=path.name)
                    db.add(row)
                row.size_bytes = stat.st_size
                row.fingerprint = fingerprint
                row.missing = False
                row.last_seen_at = utcnow()
                summary["unmatched"] += 1
                record_success(db.connection(), path, stat, unmatched_file_id=row.id)
        reconcile_missing(db.connection(), root_paths, observed_paths)
        tracked_files = db.scalars(select(MediaFile)).all()
        for media in tracked_files:
            probe = db.get(MediaProbe, media.id)
            if probe is None:
                probe = MediaProbe(media_file_id=media.id)
                db.add(probe)
            if not Path(media.path).exists():
                probe.missing = True
        unmatched_files = db.scalars(select(UnmatchedMediaFile)).all()
        for item in unmatched_files:
            if not Path(item.path).exists():
                item.missing = True
        db.commit()
    return summary


def asset_for(db: Session, media_id: int, kind: str) -> Path:
    media = db.get(MediaFile, media_id)
    if media is None:
        raise MediaLibraryError("Media file not found")
    probe = db.get(MediaProbe, media_id)
    if probe is None or probe.missing:
        probe = index_media_file(db, media, create_assets=False)
    source = Path(media.path)
    duration = probe.duration_seconds or 0.0
    position = max(1.0, min(duration * 0.25, max(duration - 1.0, 1.0))) if duration else 1.0
    root = _asset_dir(media.id)
    if kind == "thumbnail":
        path = Path(probe.thumbnail_path) if probe.thumbnail_path else root / "thumbnail.jpg"
        if not path.exists():
            _write_thumbnail(source, path, position)
            probe.thumbnail_path = str(path)
            db.commit()
        return path
    if kind == "screengrab":
        path = Path(probe.screengrab_path) if probe.screengrab_path else root / "screengrab.jpg"
        if not path.exists():
            _image_asset(source, path, position)
            probe.screengrab_path = str(path)
            db.commit()
        return path
    if kind == "preview":
        path = Path(probe.preview_path) if probe.preview_path else root / "preview.mp4"
        if not path.exists():
            start = max(0.0, min(duration * 0.2, max(duration - 12.0, 0.0))) if duration else 0.0
            _preview_asset(source, path, start)
            probe.preview_path = str(path)
            db.commit()
        return path
    raise MediaLibraryError(f"Unknown media asset: {kind}")


def media_type_for(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def ensure_browser_playback(
    media_id: int,
    source: Path,
    *,
    video_codec: str | None = None,
    audio_codec: str | None = None,
    generated_root: Path | None = None,
) -> Path:
    """Return a browser-playable file, caching an MP4 fallback when required."""
    source = Path(source)
    if not source.exists() or not source.is_file():
        raise MediaLibraryError(f"Media file does not exist: {source}")

    if video_codec is None:
        try:
            metadata = probe_path(source)
        except MediaLibraryError:
            # Preserve direct streaming for existing MP4/M4V media when probing is
            # unavailable (for example in lightweight test/dev environments).
            # Production containers include FFprobe, so incompatible MP4 codecs
            # are still detected and converted there.
            if source.suffix.casefold() in {".mp4", ".m4v"}:
                return source
            raise
        video_codec = metadata.get("video_codec")
        audio_codec = metadata.get("audio_codec")

    vcodec = (video_codec or "").casefold()
    acodec = (audio_codec or "").casefold() or None
    if source.suffix.casefold() in {".mp4", ".m4v"} and vcodec in {"h264", "avc1"} and acodec in {None, "aac", "mp3"}:
        return source

    root = (generated_root or GENERATED_ROOT) / "media" / str(media_id)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "playback.mp4"
    if target.exists() and target.stat().st_size > 0 and target.stat().st_mtime >= source.stat().st_mtime:
        return target

    temporary = root / "playback.tmp.mp4"
    temporary.unlink(missing_ok=True)
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
    ]
    if vcodec in {"h264", "avc1"}:
        command += ["-c:v", "copy"]
    else:
        command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-threads", "2"]
    if acodec is None:
        command += ["-an"]
    elif acodec == "aac":
        command += ["-c:a", "copy"]
    else:
        command += ["-c:a", "aac", "-b:a", "192k"]
    command += ["-movflags", "+faststart", str(temporary)]
    try:
        _run(command, timeout=6 * 60 * 60)
        if not temporary.exists() or temporary.stat().st_size <= 0:
            raise MediaLibraryError("FFmpeg did not create a browser playback file")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
