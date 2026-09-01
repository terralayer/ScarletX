from typing import Literal
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RemotePerson(BaseModel):
    id: str
    search_id: int | None = None
    name: str
    image_url: str | None = None
    bio: str | None = None
    aliases: list[str] = Field(default_factory=list)
    gender: str | None = None
    birthday: date | None = None
    deathday: date | None = None
    age: int | None = None
    birthplace: str | None = None
    birthplace_code: str | None = None
    nationality: str | None = None
    ethnicity: str | None = None
    measurements: str | None = None
    cup_size: str | None = None
    fake_boobs: bool | None = None
    waist: str | None = None
    hips: str | None = None
    same_sex_only: bool | None = None
    status: str | None = None
    height: str | None = None
    weight: str | None = None
    hair_color: str | None = None
    eye_color: str | None = None
    tattoos: str | None = None
    piercings: str | None = None
    astrology: str | None = None
    career_start_year: int | None = None
    career_end_year: int | None = None
    links: dict[str, str | None] = Field(default_factory=dict)


class RemoteStudio(BaseModel):
    id: str
    search_id: int | None = None
    name: str
    url: str | None = None
    logo_url: str | None = None
    poster_url: str | None = None
    description: str | None = None


class RemoteTag(BaseModel):
    id: str
    name: str


class RemoteScene(BaseModel):
    id: str
    source: str | None = None
    source_id: str | None = None
    media_type: str | None = None
    title: str
    description: str | None = None
    release_date: date | None = None
    duration: int | None = None
    source_url: str | None = None
    image_url: str | None = None
    back_image_url: str | None = None
    poster_url: str | None = None
    studio: RemoteStudio | None = None
    performers: list[RemotePerson] = Field(default_factory=list)
    tags: list[RemoteTag] = Field(default_factory=list)
    status: str | None = None


class SearchResponse(BaseModel):
    items: list[RemoteScene]
    total: int
    page: int
    per_page: int


class PerformerSearchResponse(BaseModel):
    items: list[RemotePerson]
    total: int
    page: int
    per_page: int


class StudioSearchResponse(BaseModel):
    items: list[RemoteStudio]
    total: int
    page: int
    per_page: int


class SceneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tpdb_id: str
    title: str
    description: str | None
    release_date: date | None
    image_url: str | None
    poster_url: str | None
    monitored: bool
    imported_at: datetime
    studio: RemoteStudio | None = None
    performers: list[RemotePerson] = []
    tags: list[RemoteTag] = []


class ImportRequest(BaseModel):
    monitored: bool = True


class NewznabIndexerWrite(BaseModel):
    name: str
    url: str
    api_key: str | None = None
    adult_categories: list[int] = Field(default_factory=list)
    enabled: bool = True
    rss_enabled: bool = True
    priority: int = Field(default=25, ge=1, le=50)


class GeneralSettingsWrite(BaseModel):
    app_name: str = "ScarletX"
    log_level: str = "INFO"


class ThePornDBSettingsWrite(BaseModel):
    api_key: str | None = None
    base_url: str = "https://api.theporndb.net"


class NewznabSettingsWrite(BaseModel):
    indexers: list[NewznabIndexerWrite] = Field(default_factory=list)


class FileManagementSettingsWrite(BaseModel):
    enabled: bool = False
    scene_naming_template: str = "{Studio}/{Title} ({Year}) [{Quality}]"


class AutomationSettingsWrite(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(60, ge=5, le=10080)
    batch_size: int = Field(10, ge=1, le=100)


class UsenetProviderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    host: str = Field(min_length=1, max_length=500)
    port: int = Field(default=563, ge=1, le=65535)
    username: str = Field(default="", max_length=500)
    password: str | None = None
    use_ssl: Literal[True] = True
    connections: int = Field(default=8, ge=1, le=150)
    enabled: bool = True
    priority: int = Field(default=25, ge=1, le=50)

    @field_validator("name", "host", "username", "password", mode="before")
    @classmethod
    def strip_provider_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class NativeUsenetSettingsWrite(BaseModel):
    enabled: bool = True
    providers: list[UsenetProviderWrite] = Field(default_factory=list)
    incomplete_dir: str = "./downloads/incomplete"
    complete_dir: str = "./downloads/complete"
    max_connections: int = Field(default=60, ge=1, le=200)
    max_retries: int = Field(default=2, ge=0, le=3)
    speed_limit_mb_s: float = Field(default=0, ge=0, le=10000)
    repair_enabled: bool = True
    unpack_enabled: bool = True


class UsenetProviderTestWrite(UsenetProviderWrite):
    pass


class NativeDownloadPasswordWrite(BaseModel):
    password: str = Field(default="", max_length=1000)


class GrabReleaseRequest(BaseModel):
    query: str = Field(min_length=2)
    indexer: str = Field(min_length=1)
    guid: str = Field(min_length=1)
    category: str | None = None
    scene_tpdb_id: str | None = None
    scene_title: str | None = None
    library_item_id: int | None = None


class RootFolderWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: str = Field(pattern="^scene$")
    path: str = Field(min_length=1, max_length=2000)
    is_default: bool = False
    create_missing: bool = True

    @field_validator("path")
    @classmethod
    def path_must_be_absolute(cls, value: str) -> str:
        from pathlib import Path

        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("Root folder path must be absolute")
        return str(path)


class QualityProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: str = Field(default="all", pattern="^(all|scene)$")
    allowed_qualities: list[str] = Field(default_factory=lambda: ["1080p", "720p"])
    cutoff_quality: str = "1080p"
    min_size_mb: float | None = Field(default=None, ge=0)
    max_size_mb: float | None = Field(default=None, ge=0)
    preferred_terms: list[str] = Field(default_factory=list)
    rejected_terms: list[str] = Field(default_factory=list)
    upgrades_allowed: bool = True
    is_default: bool = False


class LibraryItemSettingsWrite(BaseModel):
    root_folder_id: int | None = None
    quality_profile_id: int | None = None
    search_enabled: bool = True


class PlaybackStateWrite(BaseModel):
    position_seconds: float | None = Field(default=None, ge=0)
    favorite: bool | None = None
    played: bool = False


class RSSSettingsWrite(BaseModel):
    enabled: bool = False
    interval_minutes: int = Field(15, ge=5, le=1440)
    max_releases_per_indexer: int = Field(100, ge=10, le=1000)
    max_grabs_per_cycle: int = Field(10, ge=1, le=100)


class ReleaseProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_type: str = Field(default="all", pattern="^(all|scene)$")
    required_terms: list[str] = Field(default_factory=list)
    ignored_terms: list[str] = Field(default_factory=list)
    preferred_scores: dict[str, int] = Field(default_factory=dict)
    indexers: list[str] = Field(default_factory=list)
    enabled: bool = True


class UserTagWrite(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    label: str | None = Field(default=None, max_length=20)


class LibraryTagsWrite(BaseModel):
    tag_ids: list[int] = Field(default_factory=list)


class WebhookWrite(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=4, max_length=2000)
    events: list[str] = Field(default_factory=lambda: ["grab", "import", "failed", "upgrade"])
    headers: dict[str, str] = Field(default_factory=dict)
    secret: str | None = None
    enabled: bool = True


class ManualImportWrite(BaseModel):
    content_type: str = Field(pattern="^scene$")
    library_item_id: int
    source_path: str = Field(min_length=1, max_length=3000)
    release_title: str | None = None
    import_mode: str | None = Field(default=None, pattern="^(move|copy|hardlink)$")


class RenameRequest(BaseModel):
    execute: bool = False


class FileManagementAdvancedWrite(BaseModel):
    import_mode: str = Field(default="move", pattern="^(move|copy|hardlink)$")
    recycle_bin_path: str = ""
    minimum_free_space_gb: float = Field(default=1.0, ge=0, le=100000)


class BackupSettingsWrite(BaseModel):
    enabled: bool = True
    directory: str = "./backups"
    interval_hours: int = Field(24, ge=1, le=720)
    keep: int = Field(14, ge=1, le=365)


class SecuritySettingsWrite(BaseModel):
    api_key_enabled: bool = False
    api_key: str | None = None


class AdminCredentialsWrite(BaseModel):
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    password_confirm: str = Field(min_length=12, max_length=1024)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        return self


class AdminSetupWrite(AdminCredentialsWrite):
    setup_token: str = Field(min_length=16, max_length=512)


class LoginWrite(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def strip_login_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required")
        return value

