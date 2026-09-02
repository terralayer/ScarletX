from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

scene_performer = Table(
    "scene_performer", Base.metadata,
    Column("scene_id", ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("performer_id", ForeignKey("performers.id", ondelete="CASCADE"), primary_key=True),
)
scene_tag = Table(
    "scene_tag", Base.metadata,
    Column("scene_id", ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Studio(Base):
    __tablename__ = "studios"
    __table_args__ = (Index("ix_studios_library_name", "is_library", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tpdb_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000))
    logo_url: Mapped[str | None] = mapped_column(String(1000))
    poster_url: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str | None] = mapped_column(Text)
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    is_library: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Performer(Base):
    __tablename__ = "performers"
    __table_args__ = (Index("ix_performers_library_name", "is_library", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tpdb_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    image_url: Mapped[str | None] = mapped_column(String(1000))
    bio: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[str | None] = mapped_column(Text)
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)
    is_library: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    tpdb_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)


class Scene(Base):
    """One ScarletX adult scene."""

    __tablename__ = "scenes"
    __table_args__ = (
        Index("ix_scenes_type_imported", "content_type", "imported_at"),
        Index("ix_scenes_calendar", "content_type", "monitored", "release_date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    tpdb_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    content_type: Mapped[str] = mapped_column(String(20), default="scene", index=True)
    description: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    duration: Mapped[int | None]
    source_url: Mapped[str | None] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000))
    back_image_url: Mapped[str | None] = mapped_column(String(1000))
    poster_url: Mapped[str | None] = mapped_column(String(1000))
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    studio_id: Mapped[int | None] = mapped_column(ForeignKey("studios.id"))
    studio: Mapped[Studio | None] = relationship()
    performers: Mapped[list[Performer]] = relationship(secondary=scene_performer)
    tags: Mapped[list[Tag]] = relationship(secondary=scene_tag)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RootFolder(Base):
    __tablename__ = "root_folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(20), index=True)
    path: Mapped[str] = mapped_column(String(2000), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    create_missing: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualityProfile(Base):
    __tablename__ = "quality_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    content_type: Mapped[str] = mapped_column(String(20), default="all", index=True)
    allowed_qualities_json: Mapped[str] = mapped_column(Text, default='["2160p","1080p","720p","480p","unknown"]')
    cutoff_quality: Mapped[str] = mapped_column(String(40), default="1080p")
    min_size_mb: Mapped[float | None] = mapped_column(Float)
    max_size_mb: Mapped[float | None] = mapped_column(Float)
    preferred_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    rejected_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    upgrades_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LibraryItemConfig(Base):
    __tablename__ = "library_item_configs"
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True)
    root_folder_id: Mapped[int | None] = mapped_column(ForeignKey("root_folders.id", ondelete="SET NULL"))
    quality_profile_id: Mapped[int | None] = mapped_column(ForeignKey("quality_profiles.id", ondelete="SET NULL"))
    search_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_search_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scene: Mapped[Scene] = relationship()
    root_folder: Mapped[RootFolder | None] = relationship()
    quality_profile: Mapped[QualityProfile | None] = relationship()


class MediaFile(Base):
    __tablename__ = "media_files"
    __table_args__ = (Index("ix_media_files_scene_imported", "scene_id", "imported_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scene_id: Mapped[int] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(String(3000), unique=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    quality: Mapped[str | None] = mapped_column(String(100))
    release_title: Mapped[str | None] = mapped_column(String(1000))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    scene: Mapped[Scene] = relationship()


class MediaProbe(Base):
    __tablename__ = "media_probes"
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), primary_key=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    video_codec: Mapped[str | None] = mapped_column(String(80))
    audio_codec: Mapped[str | None] = mapped_column(String(80))
    container: Mapped[str | None] = mapped_column(String(120))
    bitrate_bps: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    file_mtime: Mapped[float | None] = mapped_column(Float)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    thumbnail_path: Mapped[str | None] = mapped_column(String(3000))
    screengrab_path: Mapped[str | None] = mapped_column(String(3000))
    preview_path: Mapped[str | None] = mapped_column(String(3000))
    missing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FileScanState(Base):
    """Durable filesystem identity used to skip unchanged scanner work."""

    __tablename__ = "file_scan_states"
    path: Mapped[str] = mapped_column(String(3000), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    mtime_ns: Mapped[int] = mapped_column(Integer)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlaybackState(Base):
    __tablename__ = "playback_states"
    media_file_id: Mapped[int] = mapped_column(ForeignKey("media_files.id", ondelete="CASCADE"), primary_key=True)
    position_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UnmatchedMediaFile(Base):
    __tablename__ = "unmatched_media_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(3000), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(1000))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    missing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class History(Base):
    __tablename__ = "history"
    __table_args__ = (
        Index("ix_history_created_at", "created_at"),
        Index("ix_history_event_type_created_at", "event_type", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scenes.id"))
    message: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_status_kind_created_at", "status", "kind", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackedDownload(Base):
    __tablename__ = "tracked_downloads"
    __table_args__ = (
        Index("ix_tracked_downloads_status_created_at", "status", "created_at"),
        Index("ix_tracked_downloads_status_last_checked_at", "status", "last_checked_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    nzo_id: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    release_title: Mapped[str] = mapped_column(String(1000))
    indexer: Mapped[str | None] = mapped_column(String(300))
    query: Mapped[str | None] = mapped_column(String(1000))
    # Historical column names are retained so existing SceneCore databases can be copied safely.
    scene_tpdb_id: Mapped[str | None] = mapped_column(String(100), index=True)
    scene_title: Mapped[str | None] = mapped_column(String(500))
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scenes.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    client_status: Mapped[str | None] = mapped_column(String(100))
    storage_path: Mapped[str | None] = mapped_column(String(2000))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NativeUsenetJob(Base):
    __tablename__ = "native_usenet_jobs"
    __table_args__ = (
        Index("ix_native_usenet_jobs_status_created_at", "status", "created_at"),
        Index("ix_native_usenet_jobs_status_updated_at", "status", "updated_at"),
    )
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(1000))
    nzb_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_bytes: Mapped[int] = mapped_column(Integer, default=0)
    speed_bps: Mapped[float] = mapped_column(Float, default=0.0)
    eta_seconds: Mapped[int | None] = mapped_column(Integer)
    output_path: Mapped[str | None] = mapped_column(String(2000))
    error: Mapped[str | None] = mapped_column(Text)
    postprocess_note: Mapped[str | None] = mapped_column(Text)
    unpack_password: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

# --- Automation / operations tables -------------------------------------------

class TrackedDownloadMeta(Base):
    __tablename__ = "tracked_download_meta"
    tracked_download_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_downloads.id", ondelete="CASCADE"), primary_key=True
    )
    download_client: Mapped[str] = mapped_column(String(50), default="scarletx", index=True)
    release_guid: Mapped[str | None] = mapped_column(String(1000), index=True)
    protocol: Mapped[str] = mapped_column(String(20), default="usenet")
    score: Mapped[int | None] = mapped_column(Integer)


class IndexerFeedItem(Base):
    __tablename__ = "indexer_feed_items"
    __table_args__ = (
        UniqueConstraint("indexer", "guid", name="uq_indexer_feed_guid"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    indexer: Mapped[str] = mapped_column(String(300), index=True)
    guid: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(String(1000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    action: Mapped[str] = mapped_column(String(50), default="ignored")
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str | None] = mapped_column(String(1000))


class ReleaseBlocklist(Base):
    __tablename__ = "release_blocklist"
    id: Mapped[int] = mapped_column(primary_key=True)
    indexer: Mapped[str | None] = mapped_column(String(300), index=True)
    guid: Mapped[str | None] = mapped_column(String(1000), index=True)
    release_title: Mapped[str] = mapped_column(String(1000), index=True)
    scene_id: Mapped[int | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str] = mapped_column(String(1000), default="Failed download")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReleaseProfile(Base):
    __tablename__ = "release_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    content_type: Mapped[str] = mapped_column(String(20), default="all", index=True)
    required_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    ignored_terms_json: Mapped[str] = mapped_column(Text, default="[]")
    preferred_scores_json: Mapped[str] = mapped_column(Text, default="{}")
    indexers_json: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


library_user_tag = Table(
    "library_user_tag", Base.metadata,
    Column("scene_id", ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("user_tags.id", ondelete="CASCADE"), primary_key=True),
)


class UserTag(Base):
    __tablename__ = "user_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    label: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Webhook(Base):
    __tablename__ = "webhooks"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2000))
    events_json: Mapped[str] = mapped_column(Text, default='["grab","import","failed","upgrade"]')
    headers_json: Mapped[str] = mapped_column(Text, default="{}")
    secret: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BackupRecord(Base):
    __tablename__ = "backup_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(3000), unique=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuthUser(Base):
    __tablename__ = "auth_users"
    __table_args__ = (
        UniqueConstraint("username_normalized", name="uq_auth_users_username_normalized"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    username_normalized: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
