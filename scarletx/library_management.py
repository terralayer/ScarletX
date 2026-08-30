from __future__ import annotations

import json
import re
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import LibraryItemConfig, MediaFile, QualityProfile, RootFolder, Scene, utcnow

VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".webm", ".mpg", ".mpeg"
}
QUALITY_ORDER = {"unknown": 0, "480p": 100, "576p": 150, "720p": 200, "1080p": 300, "2160p": 400}
SOURCE_ORDER = {"cam": -100, "telesync": -80, "hdtv": 10, "webrip": 20, "web-dl": 30, "bluray": 40, "remux": 50}
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{x}" for x in range(1, 10)), *(f"LPT{x}" for x in range(1, 10))
}


class FileImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class DetectedQuality:
    resolution: str
    source: str | None

    @property
    def label(self) -> str:
        return f"{self.resolution} {self.source}" if self.source else self.resolution


@dataclass(frozen=True)
class ReleaseScore:
    score: int
    quality: DetectedQuality
    reason: str


def detect_quality(title: str) -> DetectedQuality:
    value = title.casefold().replace("_", ".")
    resolution = "unknown"
    for pattern, label in (
        (r"(?:^|[. _-])2160p?(?:[. _-]|$)|\b4k\b|\buhd\b", "2160p"),
        (r"(?:^|[. _-])1080p?(?:[. _-]|$)", "1080p"),
        (r"(?:^|[. _-])720p?(?:[. _-]|$)", "720p"),
        (r"(?:^|[. _-])576p?(?:[. _-]|$)", "576p"),
        (r"(?:^|[. _-])480p?(?:[. _-]|$)", "480p"),
    ):
        if re.search(pattern, value, re.I):
            resolution = label
            break
    source = None
    for pattern, label in (
        (r"\bremux\b", "REMUX"),
        (r"\bblu[ ._-]?ray\b|\bbdrip\b|\bbrrip\b", "BluRay"),
        (r"\bweb[ ._-]?dl\b|\bwebdl\b", "WEB-DL"),
        (r"\bweb[ ._-]?rip\b|\bwebrip\b", "WEBRip"),
        (r"\bhdtv\b", "HDTV"),
        (r"\btelesync\b|\bts\b", "TELESYNC"),
        (r"\bcam\b", "CAM"),
    ):
        if re.search(pattern, value, re.I):
            source = label
            break
    return DetectedQuality(resolution=resolution, source=source)


def sanitize_component(value: object, fallback: str = "Unknown") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", " - ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = fallback
    if text.upper() in WINDOWS_RESERVED:
        text = f"_{text}"
    return text[:220].rstrip(" .") or fallback


def naming_template_for(settings: Settings, content_type: str) -> str:
    return settings.scene_naming_template


def render_relative_media_path(
    scene: Scene,
    release_title: str,
    settings: Settings,
) -> Path:
    quality = detect_quality(release_title)
    values = {
        "Title": sanitize_component(scene.title),
        "Studio": sanitize_component(scene.studio.name if scene.studio else "Unknown Studio"),
        "Year": scene.release_date.year if scene.release_date else "Unknown Year",
        "Quality": sanitize_component(quality.label),
        "MetadataId": sanitize_component(scene.tpdb_id),
    }
    template = settings.scene_naming_template
    try:
        rendered = template.format_map(values)
    except (KeyError, ValueError) as exc:
        raise FileImportError(f"Invalid scene naming template: {exc}") from exc
    parts = [sanitize_component(part) for part in re.split(r"[/\\]+", rendered) if part.strip()]
    if not parts:
        raise FileImportError("Naming template produced an empty path")
    return Path(*parts)

def select_primary_video(storage_path: str) -> Path:
    source = Path(storage_path).expanduser()
    if source.is_file() and source.suffix.casefold() in VIDEO_EXTENSIONS:
        return source
    if not source.exists():
        raise FileImportError(f"Completed download path does not exist: {source}")
    if not source.is_dir():
        raise FileImportError(f"Completed download path is not a directory or supported video: {source}")
    candidates = [p for p in source.rglob("*") if p.is_file() and p.suffix.casefold() in VIDEO_EXTENSIONS]
    if not candidates:
        raise FileImportError(f"No supported video file found under {source}")
    non_samples = [p for p in candidates if not re.search(r"(?:^|[. _-])(sample|trailer)(?:[. _-]|$)", p.name, re.I)]
    pool = non_samples or candidates
    return max(pool, key=lambda p: p.stat().st_size)


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    for number in range(1, 10000):
        candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileImportError(f"Could not create a unique destination for {path}")


def seed_quality_profiles(db: Session) -> None:
    if db.scalar(select(QualityProfile.id).limit(1)) is not None:
        return
    profiles = [
        QualityProfile(
            name="Standard HD",
            content_type="all",
            allowed_qualities_json=json.dumps(["1080p", "720p"]),
            cutoff_quality="1080p",
            preferred_terms_json=json.dumps(["web-dl", "bluray"]),
            rejected_terms_json=json.dumps(["cam", "telesync"]),
            is_default=True,
        ),
        QualityProfile(
            name="4K / UHD",
            content_type="all",
            allowed_qualities_json=json.dumps(["2160p", "1080p"]),
            cutoff_quality="2160p",
            preferred_terms_json=json.dumps(["remux", "bluray", "web-dl"]),
            rejected_terms_json=json.dumps(["cam", "telesync"]),
        ),
        QualityProfile(
            name="Any Quality",
            content_type="all",
            allowed_qualities_json=json.dumps(["2160p", "1080p", "720p", "576p", "480p", "unknown"]),
            cutoff_quality="1080p",
            preferred_terms_json="[]",
            rejected_terms_json=json.dumps(["cam", "telesync"]),
        ),
    ]
    db.add_all(profiles)
    db.commit()


def default_root_folder(db: Session, content_type: str) -> RootFolder | None:
    return db.scalar(
        select(RootFolder)
        .where(RootFolder.content_type == content_type)
        .order_by(RootFolder.is_default.desc(), RootFolder.id)
        .limit(1)
    )


def default_quality_profile(db: Session, content_type: str) -> QualityProfile | None:
    return db.scalar(
        select(QualityProfile)
        .where(QualityProfile.content_type.in_((content_type, "all")))
        .order_by(QualityProfile.is_default.desc(), QualityProfile.id)
        .limit(1)
    )


def ensure_library_config(db: Session, scene: Scene) -> LibraryItemConfig:
    config = db.get(LibraryItemConfig, scene.id)
    root = default_root_folder(db, scene.content_type)
    profile = default_quality_profile(db, scene.content_type)
    if config is None:
        config = LibraryItemConfig(
            scene_id=scene.id,
            root_folder_id=root.id if root else None,
            quality_profile_id=profile.id if profile else None,
            search_enabled=True,
        )
        db.add(config)
        db.flush()
    else:
        # A library item may predate root-folder configuration. Attach defaults lazily
        # once they exist so upgraded libraries begin using them without re-adding media.
        if config.root_folder_id is None and root is not None:
            config.root_folder_id = root.id
        if config.quality_profile_id is None and profile is not None:
            config.quality_profile_id = profile.id
        db.flush()
    return config


def _check_free_space(root_path: Path, source_size: int, settings: Settings) -> None:
    free = shutil.disk_usage(root_path).free
    reserve = int(max(0.0, settings.minimum_free_space_gb) * 1024**3)
    if free - source_size < reserve:
        raise FileImportError(
            f"Not enough free space in {root_path}; ScarletX keeps {settings.minimum_free_space_gb:g} GiB reserved"
        )


def _place_file(source: Path, destination: Path, mode: str) -> None:
    if source.resolve() == destination.resolve(strict=False):
        return
    if mode == "copy":
        shutil.copy2(source, destination)
        return
    if mode == "hardlink":
        try:
            os.link(source, destination)
        except OSError as exc:
            raise FileImportError(f"Could not hardlink media file: {exc}") from exc
        return
    if mode != "move":
        raise FileImportError(f"Unsupported import mode: {mode}")
    shutil.move(str(source), str(destination))


def _root_for_scene(db: Session, scene: Scene) -> tuple[RootFolder, Path]:
    config = ensure_library_config(db, scene)
    root = db.get(RootFolder, config.root_folder_id) if config.root_folder_id else default_root_folder(db, scene.content_type)
    if root is None:
        raise FileImportError(f"No {scene.content_type} root folder is configured")
    root_path = Path(root.path).expanduser()
    if not root_path.exists():
        if root.create_missing:
            root_path.mkdir(parents=True, exist_ok=True)
        else:
            raise FileImportError(f"Root folder does not exist: {root_path}")
    if not root_path.is_dir():
        raise FileImportError(f"Root folder is not a directory: {root_path}")
    return root, root_path


def import_specific_media_file(
    db: Session,
    *,
    scene: Scene,
    source: Path,
    release_title: str,
    settings: Settings,
    import_mode: str | None = None,
) -> MediaFile:
    if not source.exists() or not source.is_file() or source.suffix.casefold() not in VIDEO_EXTENSIONS:
        raise FileImportError(f"Source is not a supported media file: {source}")
    _, root_path = _root_for_scene(db, scene)
    relative = render_relative_media_path(scene, release_title, settings)
    destination = (root_path / relative).with_suffix(source.suffix.casefold())
    destination.parent.mkdir(parents=True, exist_ok=True)
    root_resolved = root_path.resolve()
    if not destination.parent.resolve().is_relative_to(root_resolved):
        raise FileImportError("Rendered media path escaped the configured root folder")
    source_resolved = source.resolve()
    final = destination if source_resolved == destination.resolve(strict=False) else unique_destination(destination)
    size = source.stat().st_size
    _check_free_space(root_path, size, settings)
    _place_file(source, final, import_mode or settings.import_mode)
    final_size = final.stat().st_size if final.exists() else size
    media = db.scalar(select(MediaFile).where(MediaFile.path == str(final)))
    if media is None:
        media = MediaFile(scene_id=scene.id, path=str(final), size_bytes=final_size, quality=detect_quality(release_title).label, release_title=release_title, imported_at=utcnow())
        db.add(media)
        db.flush()
    else:
        media.scene_id = scene.id
        media.size_bytes = final_size
        media.quality = detect_quality(release_title).label
        media.release_title = release_title
    db.flush()
    return media

def preview_media_rename(db: Session, media: MediaFile, settings: Settings) -> str:
    scene = db.get(Scene, media.scene_id)
    if scene is None:
        raise FileImportError("Media file is not linked to a scene")
    source = Path(media.path)
    if not source.exists():
        raise FileImportError(f"Media file does not exist: {source}")
    _, root_path = _root_for_scene(db, scene)
    relative = render_relative_media_path(scene, media.release_title or source.stem, settings)
    return str((root_path / relative).with_suffix(source.suffix.casefold()))

def rename_media_file(db: Session, media: MediaFile, settings: Settings) -> tuple[str, str]:
    old = Path(media.path)
    target = Path(preview_media_rename(db, media, settings))
    if old.resolve() == target.resolve(strict=False):
        return str(old), str(old)
    target.parent.mkdir(parents=True, exist_ok=True)
    final = unique_destination(target)
    shutil.move(str(old), str(final))
    media.path = str(final)
    media.size_bytes = final.stat().st_size
    db.flush()
    return str(old), str(final)


def recycle_media_file(db: Session, media: MediaFile, settings: Settings) -> str | None:
    path = Path(media.path)
    if not path.exists():
        db.delete(media)
        db.flush()
        return None
    recycle = settings.recycle_bin_path.strip()
    if recycle:
        base = Path(recycle).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        destination = unique_destination(base / path.name)
        shutil.move(str(path), str(destination))
        db.delete(media)
        db.flush()
        return str(destination)
    path.unlink()
    db.delete(media)
    db.flush()
    return None


def scan_path_for_manual_import(path: str) -> list[dict]:
    root = Path(path).expanduser()
    if not root.exists():
        raise FileImportError(f"Import path does not exist: {root}")
    files = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
    rows = []
    for item in files:
        if item.suffix.casefold() not in VIDEO_EXTENSIONS:
            continue
        rows.append({
            "path": str(item),
            "name": item.name,
            "size_bytes": item.stat().st_size,
            "quality": detect_quality(item.name).label,
        })
    rows.sort(key=lambda row: row["size_bytes"], reverse=True)
    return rows


def import_media_file(
    db: Session,
    *,
    scene: Scene,
    release_title: str,
    storage_path: str,
    settings: Settings,
    import_mode: str | None = None,
) -> MediaFile:
    source = select_primary_video(storage_path)
    return import_specific_media_file(
        db, scene=scene, source=source, release_title=release_title or source.name,
        settings=settings, import_mode=import_mode,
    )

def _json_list(value: str) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item).strip().casefold() for item in data if str(item).strip()]


def score_release(title: str, size: int | None, profile: QualityProfile) -> ReleaseScore | None:
    lowered = title.casefold()
    rejected = _json_list(profile.rejected_terms_json)
    rejected_match = next((term for term in rejected if term in lowered), None)
    if rejected_match:
        return None

    size_mb = (size / 1024 / 1024) if size else None
    if size_mb is not None and profile.min_size_mb is not None and size_mb < profile.min_size_mb:
        return None
    if size_mb is not None and profile.max_size_mb is not None and size_mb > profile.max_size_mb:
        return None

    quality = detect_quality(title)
    allowed = set(_json_list(profile.allowed_qualities_json))
    if allowed and quality.resolution.casefold() not in allowed:
        return None

    score = QUALITY_ORDER.get(quality.resolution, 0) * 10
    if quality.source:
        score += SOURCE_ORDER.get(quality.source.casefold(), 0)
    preferred = _json_list(profile.preferred_terms_json)
    score += 75 * sum(1 for term in preferred if term in lowered)
    cutoff = QUALITY_ORDER.get(profile.cutoff_quality.casefold(), 0)
    if QUALITY_ORDER.get(quality.resolution, 0) >= cutoff:
        score += 250
    return ReleaseScore(score=score, quality=quality, reason=f"{quality.label} matched {profile.name}")
