import asyncio
import base64
import json
import os
import shutil
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Response, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, ORJSONResponse, StreamingResponse
from pydantic import SecretStr
from sqlalchemy import and_, delete, func, inspect, or_, select, text, update
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..db import Base, SessionLocal, engine, get_session
from ..models import (
    AuthUser, BackgroundJob, BackupRecord, History, IndexerFeedItem, LibraryItemConfig,
    MediaFile, MediaProbe, NativeUsenetJob, Performer, PlaybackState, QualityProfile, ReleaseBlocklist, ReleaseProfile,
    RootFolder, Scene, Studio, TrackedDownload, TrackedDownloadMeta, UnmatchedMediaFile,
    UserTag, Webhook, library_user_tag, utcnow,
)
from ..newznab import NewznabClient, NewznabError, close_shared_newznab_clients
from ..metadata import MetadataProviderError, metadata_client, metadata_provider_status
from ..tpdb import close_shared_tpdb_clients
from ..automation import automatic_search_cycle, grab_specific_release, search_and_grab_scene
from ..library_management import (
    FileImportError, ensure_library_config, import_specific_media_file,
    preview_media_rename, recycle_media_file, rename_media_file, scan_path_for_manual_import,
    seed_quality_profiles,
)
from ..schemas import (
    AutomationSettingsWrite,
    FileManagementSettingsWrite,
    GeneralSettingsWrite,
    GrabReleaseRequest,
    ImportRequest,
    LibraryItemSettingsWrite,
    NewznabSettingsWrite,
    NativeUsenetSettingsWrite,
    NativeDownloadPasswordWrite,
    PlaybackStateWrite,
    UsenetProviderTestWrite,
    PerformerSearchResponse,
    RemotePerson,
    RemoteScene,
    RemoteStudio,
    RootFolderWrite,
    QualityProfileWrite,
    SearchResponse,
    StudioSearchResponse,
    ThePornDBSettingsWrite,
    BackupSettingsWrite,
    FileManagementAdvancedWrite,
    LibraryTagsWrite,
    ManualImportWrite,
    ReleaseProfileWrite,
    RenameRequest,
    RSSSettingsWrite,
    SecuritySettingsWrite,
    UserTagWrite,
    WebhookWrite,
)
from ..download_clients import DownloadClientError, resolve_client, submit_release
from ..native_usenet import (
    NativeUsenetError, UsenetProviderConfig, completed_rows as native_completed_rows,
    history_rows as native_history_rows, failed_rows as native_failed_rows, job_dict as native_job_dict,
    native_client_ready, native_worker_loop, queue_rows as native_queue_rows, request_cancel as request_native_cancel,
    test_provider as test_native_provider, tool_status as native_tool_status, reprocess_completed_job as reprocess_native_completed_job,
)
from ..services import repair_legacy_auto_monitored_adult_entities, sync_adult_scene_entities_to_library, upsert_performer, upsert_scene, upsert_studio
from ..backups import BackupError, create_backup, list_backups
from ..download_processing import process_completed_downloads as process_downloads_core
from ..notifications import emit_webhooks
from ..rss import rss_sync_cycle
from ..wanted import calendar_items, cutoff_unmet, disk_space, missing_items
from ..settings_store import load_database_settings, seed_database_settings, set_setting
from ..setup_security import ensure_setup_token
from ..studio_art import StudioArtworkError, cache_studio_artwork, cached_studio_artwork, download_and_prepare_studio_artwork
from ..media_library import (
    MediaLibraryError, asset_for, duplicate_rows, index_media_file, index_media_file_by_id,
    library_stats, media_row, media_rows, media_type_for, scan_library, tool_status as media_tool_status, update_playback,
)
from ..media_watch import media_watch_loop
from ..remote_art import RemoteArtworkError, cached_remote_image, cached_remote_thumbnail, close_remote_art_client
from ..status_console import collect_startup_status, emit_status, render_dashboard
from ..migrations import (
    ensure_file_scan_state_table,
    ensure_performance_indexes,
    performance_index_migration_required,
)
from ..list_queries import performer_summary_page, scene_summary_page, studio_summary_page
from ..event_stream import QueueEvent, format_sse, queue_event_broker, queue_event_pump


def _encode_cursor(*parts) -> str:
    raw = json.dumps(parts, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> list:
    if not value:
        return []
    try:
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        return data if isinstance(data, list) else []
    except Exception:
        raise HTTPException(400, "Invalid pagination cursor")


def migrate_to_scarletx(db: Session) -> None:
    """Remove non-adult SceneCore records from the copied ScarletX database."""
    tables = set(inspect(db.bind).get_table_names())
    legacy_ids = [row[0] for row in db.execute(text("SELECT id FROM scenes WHERE content_type <> 'scene'"))] if "scenes" in tables else []
    if legacy_ids:
        params = {f"id{i}": value for i, value in enumerate(legacy_ids)}
        slots = ",".join(f":id{i}" for i in range(len(legacy_ids)))
        for table, column in (("history","scene_id"),("indexer_feed_items","scene_id"),("release_blocklist","scene_id"),("tracked_downloads","scene_id")):
            if table in tables:
                db.execute(text(f"UPDATE {table} SET {column}=NULL WHERE {column} IN ({slots})"), params)
        if "episode_files" in tables and "media_files" in tables:
            db.execute(text(f"DELETE FROM episode_files WHERE media_file_id IN (SELECT id FROM media_files WHERE scene_id IN ({slots}))"), params)
        if "tv_episodes" in tables:
            if "indexer_feed_items" in tables:
                cols = {c['name'] for c in inspect(db.bind).get_columns('indexer_feed_items')}
                if 'episode_id' in cols:
                    db.execute(text(f"UPDATE indexer_feed_items SET episode_id=NULL WHERE episode_id IN (SELECT id FROM tv_episodes WHERE scene_id IN ({slots}))"), params)
            if "episode_files" in tables:
                db.execute(text(f"DELETE FROM episode_files WHERE episode_id IN (SELECT id FROM tv_episodes WHERE scene_id IN ({slots}))"), params)
            db.execute(text(f"DELETE FROM tv_episodes WHERE scene_id IN ({slots})"), params)
        for table in ("tv_seasons", "tv_show_options", "library_user_tag", "media_files", "library_item_configs"):
            if table in tables:
                db.execute(text(f"DELETE FROM {table} WHERE scene_id IN ({slots})"), params)
        db.execute(text(f"DELETE FROM scenes WHERE id IN ({slots})"), params)
    if "root_folders" in tables:
        db.execute(text("DELETE FROM root_folders WHERE content_type <> 'scene'"))
    if "quality_profiles" in tables:
        db.execute(text("DELETE FROM quality_profiles WHERE content_type IN ('movie','tv')"))
    if "release_profiles" in tables:
        db.execute(text("DELETE FROM release_profiles WHERE content_type IN ('movie','tv')"))
    if "tracked_download_meta" in tables and "tracked_downloads" in tables:
        bad = [row[0] for row in db.execute(text("SELECT tracked_download_id FROM tracked_download_meta WHERE download_client <> 'scarletx'"))]
        if bad:
            params = {f"d{i}": value for i, value in enumerate(bad)}
            slots = ",".join(f":d{i}" for i in range(len(bad)))
            db.execute(text(f"DELETE FROM tracked_download_meta WHERE tracked_download_id IN ({slots})"), params)
            db.execute(text(f"DELETE FROM tracked_downloads WHERE id IN ({slots})"), params)
    db.commit()

    # On copied SQLite databases, remove the obsolete TV/episode schema itself.
    # Fresh ScarletX databases never create these tables/columns.
    if engine.url.get_backend_name() == "sqlite":
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            legacy_tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "indexer_feed_items" in legacy_tables:
                columns = {row[1] for row in cur.execute("PRAGMA table_info(indexer_feed_items)")}
                if "episode_id" in columns:
                    cur.executescript("""
                    CREATE TABLE indexer_feed_items_scarletx (
                        id INTEGER NOT NULL PRIMARY KEY,
                        indexer VARCHAR(300) NOT NULL,
                        guid VARCHAR(1000) NOT NULL,
                        title VARCHAR(1000) NOT NULL,
                        published_at DATETIME,
                        seen_at DATETIME NOT NULL,
                        action VARCHAR(50) NOT NULL,
                        scene_id INTEGER,
                        reason VARCHAR(1000),
                        CONSTRAINT uq_indexer_feed_guid UNIQUE (indexer, guid),
                        FOREIGN KEY(scene_id) REFERENCES scenes (id) ON DELETE SET NULL
                    );
                    INSERT INTO indexer_feed_items_scarletx
                        (id,indexer,guid,title,published_at,seen_at,action,scene_id,reason)
                    SELECT id,indexer,guid,title,published_at,seen_at,action,scene_id,reason
                    FROM indexer_feed_items;
                    DROP TABLE indexer_feed_items;
                    ALTER TABLE indexer_feed_items_scarletx RENAME TO indexer_feed_items;
                    CREATE INDEX IF NOT EXISTS ix_indexer_feed_items_indexer ON indexer_feed_items (indexer);
                    CREATE INDEX IF NOT EXISTS ix_indexer_feed_items_seen_at ON indexer_feed_items (seen_at);
                    CREATE INDEX IF NOT EXISTS ix_indexer_feed_items_scene_id ON indexer_feed_items (scene_id);
                    """)
            if "tracked_downloads" in legacy_tables:
                columns = {row[1] for row in cur.execute("PRAGMA table_info(tracked_downloads)")}
                if "sab_status" in columns and "client_status" not in columns:
                    cur.execute("ALTER TABLE tracked_downloads RENAME COLUMN sab_status TO client_status")
            if "tracked_download_meta" in legacy_tables:
                columns = {row[1] for row in cur.execute("PRAGMA table_info(tracked_download_meta)")}
                if "episode_ids_json" in columns:
                    cur.executescript("""
                    CREATE TABLE tracked_download_meta_scarletx (
                        tracked_download_id INTEGER NOT NULL PRIMARY KEY,
                        download_client VARCHAR(50) NOT NULL,
                        release_guid VARCHAR(1000),
                        protocol VARCHAR(20) NOT NULL,
                        score INTEGER,
                        FOREIGN KEY(tracked_download_id) REFERENCES tracked_downloads (id) ON DELETE CASCADE
                    );
                    INSERT INTO tracked_download_meta_scarletx
                        (tracked_download_id,download_client,release_guid,protocol,score)
                    SELECT tracked_download_id,download_client,release_guid,protocol,score
                    FROM tracked_download_meta;
                    DROP TABLE tracked_download_meta;
                    ALTER TABLE tracked_download_meta_scarletx RENAME TO tracked_download_meta;
                    CREATE INDEX IF NOT EXISTS ix_tracked_download_meta_download_client ON tracked_download_meta (download_client);
                    CREATE INDEX IF NOT EXISTS ix_tracked_download_meta_release_guid ON tracked_download_meta (release_guid);
                    """)
            for table in ("episode_files", "tv_episodes", "tv_seasons", "tv_show_options", "remote_path_mappings"):
                cur.execute(f"DROP TABLE IF EXISTS {table}")
            # Composite indexes used by paged library and future-release queries.
            cur.executescript("""
            CREATE INDEX IF NOT EXISTS ix_scenes_type_imported ON scenes (content_type, imported_at);
            CREATE INDEX IF NOT EXISTS ix_scenes_calendar ON scenes (content_type, monitored, release_date);
            CREATE INDEX IF NOT EXISTS ix_performers_library_name ON performers (is_library, name);
            CREATE INDEX IF NOT EXISTS ix_studios_library_name ON studios (is_library, name);
            CREATE INDEX IF NOT EXISTS ix_media_files_scene_imported ON media_files (scene_id, imported_at);
            CREATE INDEX IF NOT EXISTS ix_history_created_at ON history (created_at);
            """)
            # FTS5 keeps local library searches fast even when metadata grows into
            # the hundreds of thousands of rows. Triggers keep it synchronized.
            try:
                cur.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS scene_search USING fts5(title);
                CREATE VIRTUAL TABLE IF NOT EXISTS performer_search USING fts5(name, aliases);
                CREATE VIRTUAL TABLE IF NOT EXISTS studio_search USING fts5(name);
                CREATE TRIGGER IF NOT EXISTS scene_search_ai AFTER INSERT ON scenes BEGIN INSERT INTO scene_search(rowid,title) VALUES(new.id,new.title); END;
                CREATE TRIGGER IF NOT EXISTS scene_search_ad AFTER DELETE ON scenes BEGIN DELETE FROM scene_search WHERE rowid=old.id; END;
                CREATE TRIGGER IF NOT EXISTS scene_search_au AFTER UPDATE OF title ON scenes BEGIN DELETE FROM scene_search WHERE rowid=old.id; INSERT INTO scene_search(rowid,title) VALUES(new.id,new.title); END;
                CREATE TRIGGER IF NOT EXISTS performer_search_ai AFTER INSERT ON performers BEGIN INSERT INTO performer_search(rowid,name,aliases) VALUES(new.id,new.name,coalesce(new.aliases,'')); END;
                CREATE TRIGGER IF NOT EXISTS performer_search_ad AFTER DELETE ON performers BEGIN DELETE FROM performer_search WHERE rowid=old.id; END;
                CREATE TRIGGER IF NOT EXISTS performer_search_au AFTER UPDATE OF name,aliases ON performers BEGIN DELETE FROM performer_search WHERE rowid=old.id; INSERT INTO performer_search(rowid,name,aliases) VALUES(new.id,new.name,coalesce(new.aliases,'')); END;
                CREATE TRIGGER IF NOT EXISTS studio_search_ai AFTER INSERT ON studios BEGIN INSERT INTO studio_search(rowid,name) VALUES(new.id,new.name); END;
                CREATE TRIGGER IF NOT EXISTS studio_search_ad AFTER DELETE ON studios BEGIN DELETE FROM studio_search WHERE rowid=old.id; END;
                CREATE TRIGGER IF NOT EXISTS studio_search_au AFTER UPDATE OF name ON studios BEGIN DELETE FROM studio_search WHERE rowid=old.id; INSERT INTO studio_search(rowid,name) VALUES(new.id,new.name); END;
                """)
                # Existing triggers keep FTS synchronized. Backfill only missing
                # rows so normal startup does not rewrite every search record.
                cur.executescript("""
                INSERT INTO scene_search(rowid,title) SELECT id,title FROM scenes WHERE id NOT IN (SELECT rowid FROM scene_search);
                INSERT INTO performer_search(rowid,name,aliases) SELECT id,name,coalesce(aliases,'') FROM performers WHERE id NOT IN (SELECT rowid FROM performer_search);
                INSERT INTO studio_search(rowid,name) SELECT id,name FROM studios WHERE id NOT IN (SELECT rowid FROM studio_search);
                """)
            except Exception:
                # Some custom SQLite builds omit FTS5; LIKE remains the fallback.
                pass
            raw.commit()
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            raw.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        # In-process background tasks cannot survive a container restart. Leaving
        # them marked active makes later Monitor All requests look like duplicates.
        interrupted = db.scalars(
            select(BackgroundJob).where(BackgroundJob.status.in_(("queued", "running")))
        ).all()
        for job in interrupted:
            job.status = "failed"
            job.error = "Interrupted by application restart"
            job.finished_at = utcnow()
        if interrupted:
            db.commit()
        seed_database_settings(db)
        with engine.connect() as connection:
            needs_performance_index_migration = performance_index_migration_required(connection)
        if needs_performance_index_migration:
            migration_settings = load_database_settings(db)
            create_backup(
                db,
                migration_settings.backup_directory,
                migration_settings.backup_keep,
            )
        migrate_to_scarletx(db)
        with engine.begin() as connection:
            ensure_file_scan_state_table(connection)
            ensure_performance_indexes(connection)
        setup_token = ensure_setup_token(admin_exists=db.scalar(select(AuthUser.id).limit(1)) is not None)
        if setup_token:
            print(f"ScarletX first-run setup token: {setup_token}", flush=True)
        seed_quality_profiles(db)
        default_media_root = os.getenv("SCARLETX_DEFAULT_MEDIA_ROOT", "").strip()
        if default_media_root and db.scalar(select(RootFolder.id).where(RootFolder.content_type == "scene").limit(1)) is None:
            db.add(RootFolder(name="Scenes", content_type="scene", path=default_media_root, is_default=True, create_missing=True))
            db.commit()
        sync_adult_scene_entities_to_library(db)
        repair_legacy_auto_monitored_adult_entities(db)
        runtime = load_database_settings(db)
        app.title = f"{runtime.app_name} API"
        try:
            print(render_dashboard(collect_startup_status(db, runtime), version="0.3.10-beta.1"), flush=True)
        except Exception as exc:
            emit_status("Status Console", "FAILED", exc.__class__.__name__, severity="error")
    def _runtime_settings_loader():
        with SessionLocal() as runtime_db:
            return load_database_settings(runtime_db)

    watchers = [
        asyncio.create_task(native_worker_loop(SessionLocal, _runtime_settings_loader)),
        asyncio.create_task(completed_download_import_loop()),
        asyncio.create_task(automatic_search_loop()),
        asyncio.create_task(rss_sync_loop()),
        asyncio.create_task(backup_loop()),
        asyncio.create_task(media_watch_loop(SessionLocal)),
        asyncio.create_task(queue_event_pump(_load_cached_activity_queue_data)),
    ]
    emit_status("Background Workers", "ACTIVE", f"{len(watchers)} workers", severity="active")
    try:
        yield
    finally:
        for watcher in watchers:
            watcher.cancel()
        for watcher in watchers:
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        await close_shared_tpdb_clients()
        await close_shared_newznab_clients()
        await close_remote_art_client()
        emit_status("Background Workers", "STOPPED", "shutdown complete", severity="ok")


app = FastAPI(title="ScarletX API", version="0.3.10-beta.1", lifespan=lifespan, default_response_class=ORJSONResponse)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


@app.middleware("http")
async def optional_api_key_auth(request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path in {"/api/health"}:
        return await call_next(request)
    try:
        with SessionLocal() as db:
            settings = load_database_settings(db)
    except Exception:
        # Database bootstrap/upgrade must remain reachable during startup failures.
        return await call_next(request)
    if not settings.api_key_enabled:
        return await call_next(request)
    expected = settings.api_key.get_secret_value()
    supplied = request.headers.get("X-Api-Key") or request.query_params.get("apikey") or ""
    auth = request.headers.get("Authorization") or ""
    if not supplied and auth.casefold().startswith("bearer "):
        supplied = auth[7:].strip()
    import secrets
    if not expected or not secrets.compare_digest(supplied, expected):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "ScarletX API key is required"}, status_code=401)
    return await call_next(request)






def get_runtime_settings(db: Session = Depends(get_session)) -> Settings:
    return load_database_settings(db)


def client(settings: Settings):
    return metadata_client(settings)


@app.get("/api/settings")
def database_settings(db: Session = Depends(get_session)):
    settings = load_database_settings(db)
    return {
        "storage": "database",
        "general": {"app_name": settings.app_name, "log_level": settings.scarletx_log_level},
        "theporndb": {
            "configured": bool(settings.theporndb_api_key.get_secret_value()),
            "base_url": settings.theporndb_base_url,
        },
        "newznab_indexers": [
            {
                "name": item.name, "url": item.url, "adult_categories": item.adult_categories,
                "enabled": item.enabled,
                "rss_enabled": item.rss_enabled, "priority": item.priority,
                "api_key_configured": bool(item.api_key.get_secret_value()),
            }
            for item in settings.newznab_indexers()
        ],
        "native_usenet": {
            "enabled": settings.native_usenet_enabled,
            "configured": native_client_ready(settings),
            "providers": [
                {
                    "name": item.name, "host": item.host, "port": item.port, "username": item.username,
                    "password_configured": bool(item.password.get_secret_value()), "use_ssl": item.use_ssl,
                    "connections": item.connections, "enabled": item.enabled, "priority": item.priority,
                }
                for item in settings.native_usenet_providers()
            ],
            "incomplete_dir": settings.native_usenet_incomplete_dir,
            "complete_dir": settings.native_usenet_complete_dir,
            "max_connections": settings.native_usenet_max_connections,
            "max_retries": settings.native_usenet_max_retries,
            "speed_limit_mb_s": settings.native_usenet_speed_limit_mb_s,
            "repair_enabled": settings.native_usenet_repair_enabled,
            "unpack_enabled": settings.native_usenet_unpack_enabled,
            "tools": native_tool_status(),
        },
        "file_management": {
            "enabled": settings.file_management_enabled,
            "scene_naming_template": settings.scene_naming_template,
            "import_mode": settings.import_mode,
            "recycle_bin_path": settings.recycle_bin_path,
            "minimum_free_space_gb": settings.minimum_free_space_gb,
        },
        "automation": {"enabled": settings.automatic_search_enabled, "interval_minutes": settings.automatic_search_interval_minutes, "batch_size": settings.automatic_search_batch_size},
        "rss": {"enabled": settings.rss_sync_enabled, "interval_minutes": settings.rss_sync_interval_minutes, "max_releases_per_indexer": settings.rss_max_releases_per_indexer, "max_grabs_per_cycle": settings.rss_max_grabs_per_cycle},
        "backups": {"enabled": settings.backup_enabled, "directory": settings.backup_directory, "interval_hours": settings.backup_interval_hours, "keep": settings.backup_keep},
        "security": {"api_key_enabled": settings.api_key_enabled, "api_key_configured": bool(settings.api_key.get_secret_value())},
        "scarletx_log_level": settings.scarletx_log_level,
    }



def serialize_indexers_with_preserved_keys(indexers, current: Settings) -> str:
    existing = {(item.name.strip().lower(), item.url.rstrip("/")): item for item in current.newznab_indexers()}
    serialized = []
    for item in indexers:
        data = item.model_dump()
        if not data.get("api_key"):
            match = existing.get((item.name.strip().lower(), item.url.rstrip("/")))
            data["api_key"] = match.api_key.get_secret_value() if match else ""
        serialized.append(data)
    return json.dumps(serialized)



@app.patch("/api/settings/general")
def update_general_settings(request: GeneralSettingsWrite, db: Session = Depends(get_session)):
    set_setting(db, "app_name", request.app_name.strip() or "ScarletX", commit=False)
    set_setting(db, "scarletx_log_level", request.log_level.strip().upper() or "INFO", commit=False)
    db.commit()
    settings = load_database_settings(db)
    app.title = f"{settings.app_name} API"
    return database_settings(db)["general"]







@app.patch("/api/settings/theporndb")
def update_theporndb_settings(
    request: ThePornDBSettingsWrite,
    db: Session = Depends(get_session),
):
    current = load_database_settings(db)
    api_key = request.api_key or current.theporndb_api_key.get_secret_value()
    set_setting(db, "theporndb_api_key", api_key, commit=False)
    set_setting(db, "theporndb_base_url", request.base_url.rstrip("/"), commit=False)
    db.commit()
    return database_settings(db)["theporndb"]


@app.patch("/api/settings/newznab")
def update_newznab_settings(
    request: NewznabSettingsWrite,
    db: Session = Depends(get_session),
):
    current = load_database_settings(db)
    set_setting(
        db,
        "newznab_indexers_json",
        serialize_indexers_with_preserved_keys(request.indexers, current),
        commit=False,
    )
    db.commit()
    return database_settings(db)["newznab_indexers"]




def _serialize_usenet_providers_with_preserved_passwords(providers, current: Settings) -> str:
    existing = {(item.name.strip().casefold(), item.host.strip().casefold(), item.port): item for item in current.native_usenet_providers()}
    rows = []
    for item in providers:
        data = item.model_dump()
        match = existing.get((item.name.strip().casefold(), item.host.strip().casefold(), item.port))
        if not data.get("password") and match:
            data["password"] = match.password.get_secret_value()
        data["password"] = data.get("password") or ""
        rows.append(data)
    return json.dumps(rows)


@app.patch("/api/settings/native-usenet")
def update_native_usenet_settings(request: NativeUsenetSettingsWrite, db: Session = Depends(get_session)):
    current = load_database_settings(db)
    set_setting(db, "native_usenet_enabled", "true" if request.enabled else "false", commit=False)
    set_setting(db, "native_usenet_providers_json", _serialize_usenet_providers_with_preserved_passwords(request.providers, current), commit=False)
    set_setting(db, "native_usenet_incomplete_dir", request.incomplete_dir, commit=False)
    set_setting(db, "native_usenet_complete_dir", request.complete_dir, commit=False)
    set_setting(db, "native_usenet_max_connections", str(request.max_connections), commit=False)
    set_setting(db, "native_usenet_max_retries", str(request.max_retries), commit=False)
    set_setting(db, "native_usenet_speed_limit_mb_s", str(request.speed_limit_mb_s), commit=False)
    set_setting(db, "native_usenet_repair_enabled", "true" if request.repair_enabled else "false", commit=False)
    set_setting(db, "native_usenet_unpack_enabled", "true" if request.unpack_enabled else "false", commit=False)
    db.commit()
    return database_settings(db)["native_usenet"]



@app.patch("/api/settings/file-management")
def update_file_management_settings(request: FileManagementSettingsWrite, db: Session = Depends(get_session)):
    set_setting(db, "file_management_enabled", "true" if request.enabled else "false", commit=False)
    set_setting(db, "scene_naming_template", request.scene_naming_template, commit=False)
    db.commit()
    return database_settings(db)["file_management"]



@app.patch("/api/settings/automation")
def update_automation_settings(
    request: AutomationSettingsWrite,
    db: Session = Depends(get_session),
):
    set_setting(db, "automatic_search_enabled", "true" if request.enabled else "false", commit=False)
    set_setting(db, "automatic_search_interval_minutes", str(request.interval_minutes), commit=False)
    set_setting(db, "automatic_search_batch_size", str(request.batch_size), commit=False)
    db.commit()
    return database_settings(db)["automation"]


@app.patch("/api/settings/rss")
def update_rss_settings(request: RSSSettingsWrite, db: Session = Depends(get_session)):
    set_setting(db, "rss_sync_enabled", "true" if request.enabled else "false", commit=False)
    set_setting(db, "rss_sync_interval_minutes", str(request.interval_minutes), commit=False)
    set_setting(db, "rss_max_releases_per_indexer", str(request.max_releases_per_indexer), commit=False)
    set_setting(db, "rss_max_grabs_per_cycle", str(request.max_grabs_per_cycle), commit=False)
    db.commit()
    return database_settings(db)["rss"]


@app.patch("/api/settings/file-management/advanced")
def update_file_management_advanced(request: FileManagementAdvancedWrite, db: Session = Depends(get_session)):
    set_setting(db, "import_mode", request.import_mode, commit=False)
    set_setting(db, "recycle_bin_path", request.recycle_bin_path, commit=False)
    set_setting(db, "minimum_free_space_gb", str(request.minimum_free_space_gb), commit=False)
    db.commit()
    return database_settings(db)["file_management"]




@app.patch("/api/settings/backups")
def update_backup_settings(request: BackupSettingsWrite, db: Session = Depends(get_session)):
    set_setting(db, "backup_enabled", "true" if request.enabled else "false", commit=False)
    set_setting(db, "backup_directory", request.directory, commit=False)
    set_setting(db, "backup_interval_hours", str(request.interval_hours), commit=False)
    set_setting(db, "backup_keep", str(request.keep), commit=False)
    db.commit()
    return database_settings(db)["backups"]


@app.patch("/api/settings/security")
def update_security_settings(request: SecuritySettingsWrite, db: Session = Depends(get_session)):
    current = load_database_settings(db)
    key = request.api_key or current.api_key.get_secret_value()
    generated = bool(request.api_key_enabled and not key)
    if generated:
        import secrets
        key = secrets.token_urlsafe(32)
    set_setting(db, "api_key_enabled", "true" if request.api_key_enabled else "false", commit=False)
    set_setting(db, "api_key", key, commit=False)
    db.commit()
    result = database_settings(db)["security"]
    if request.api_key_enabled and (request.api_key or generated):
        result["api_key"] = key
    return result


def _root_folder_dict(item: RootFolder) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "content_type": item.content_type,
        "path": item.path,
        "is_default": item.is_default,
        "create_missing": item.create_missing,
    }


def _quality_profile_dict(item: QualityProfile) -> dict:
    def values(raw: str) -> list[str]:
        try:
            return list(json.loads(raw or "[]"))
        except (json.JSONDecodeError, TypeError):
            return []
    return {
        "id": item.id,
        "name": item.name,
        "content_type": item.content_type,
        "allowed_qualities": values(item.allowed_qualities_json),
        "cutoff_quality": item.cutoff_quality,
        "min_size_mb": item.min_size_mb,
        "max_size_mb": item.max_size_mb,
        "preferred_terms": values(item.preferred_terms_json),
        "rejected_terms": values(item.rejected_terms_json),
        "upgrades_allowed": item.upgrades_allowed,
        "is_default": item.is_default,
    }


@app.get("/api/root-folders")
def root_folders(db: Session = Depends(get_session)):
    return [_root_folder_dict(item) for item in db.scalars(select(RootFolder).where(RootFolder.content_type == "scene").order_by(RootFolder.name)).all()]



def _save_root_folder(db: Session, request: RootFolderWrite, item: RootFolder | None = None) -> RootFolder:
    if item is None:
        item = RootFolder(name=request.name, content_type=request.content_type, path=request.path)
        db.add(item)
    if request.is_default:
        for existing in db.scalars(select(RootFolder).where(RootFolder.content_type == request.content_type)).all():
            existing.is_default = False
    item.name = request.name.strip()
    item.content_type = request.content_type
    item.path = request.path
    item.is_default = request.is_default
    item.create_missing = request.create_missing
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/root-folders", status_code=201)
def create_root_folder(request: RootFolderWrite, db: Session = Depends(get_session)):
    existing = db.scalar(select(RootFolder).where(RootFolder.path == request.path))
    if existing:
        raise HTTPException(409, "That root folder path is already configured")
    return _root_folder_dict(_save_root_folder(db, request))


@app.put("/api/root-folders/{folder_id}")
def update_root_folder(folder_id: int, request: RootFolderWrite, db: Session = Depends(get_session)):
    item = db.get(RootFolder, folder_id)
    if item is None:
        raise HTTPException(404, "Root folder not found")
    duplicate = db.scalar(select(RootFolder).where(RootFolder.path == request.path, RootFolder.id != folder_id))
    if duplicate:
        raise HTTPException(409, "That root folder path is already configured")
    return _root_folder_dict(_save_root_folder(db, request, item))


@app.delete("/api/root-folders/{folder_id}", status_code=204)
def delete_root_folder(folder_id: int, db: Session = Depends(get_session)):
    item = db.get(RootFolder, folder_id)
    if item is None:
        raise HTTPException(404, "Root folder not found")
    for config in db.scalars(select(LibraryItemConfig).where(LibraryItemConfig.root_folder_id == folder_id)).all():
        config.root_folder_id = None
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@app.get("/api/quality-profiles")
def quality_profiles(db: Session = Depends(get_session)):
    items=db.scalars(select(QualityProfile).where(QualityProfile.content_type.in_(("all","scene"))).order_by(QualityProfile.is_default.desc(), QualityProfile.name)).all()
    return [_quality_profile_dict(item) for item in items]



def _save_quality_profile(db: Session, request: QualityProfileWrite, item: QualityProfile | None = None) -> QualityProfile:
    if item is None:
        item = QualityProfile(name=request.name)
        db.add(item)
    if request.is_default:
        for existing in db.scalars(select(QualityProfile).where(QualityProfile.content_type == request.content_type)).all():
            existing.is_default = False
    item.name = request.name.strip()
    item.content_type = request.content_type
    item.allowed_qualities_json = json.dumps(request.allowed_qualities)
    item.cutoff_quality = request.cutoff_quality
    item.min_size_mb = request.min_size_mb
    item.max_size_mb = request.max_size_mb
    item.preferred_terms_json = json.dumps(request.preferred_terms)
    item.rejected_terms_json = json.dumps(request.rejected_terms)
    item.upgrades_allowed = request.upgrades_allowed
    item.is_default = request.is_default
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/quality-profiles", status_code=201)
def create_quality_profile(request: QualityProfileWrite, db: Session = Depends(get_session)):
    if db.scalar(select(QualityProfile).where(QualityProfile.name == request.name.strip())):
        raise HTTPException(409, "A quality profile with that name already exists")
    return _quality_profile_dict(_save_quality_profile(db, request))


@app.put("/api/quality-profiles/{profile_id}")
def update_quality_profile(profile_id: int, request: QualityProfileWrite, db: Session = Depends(get_session)):
    item = db.get(QualityProfile, profile_id)
    if item is None:
        raise HTTPException(404, "Quality profile not found")
    duplicate = db.scalar(select(QualityProfile).where(QualityProfile.name == request.name.strip(), QualityProfile.id != profile_id))
    if duplicate:
        raise HTTPException(409, "A quality profile with that name already exists")
    return _quality_profile_dict(_save_quality_profile(db, request, item))


@app.delete("/api/quality-profiles/{profile_id}", status_code=204)
def delete_quality_profile(profile_id: int, db: Session = Depends(get_session)):
    item = db.get(QualityProfile, profile_id)
    if item is None:
        raise HTTPException(404, "Quality profile not found")
    for config in db.scalars(select(LibraryItemConfig).where(LibraryItemConfig.quality_profile_id == profile_id)).all():
        config.quality_profile_id = None
    db.delete(item)
    db.commit()
    return Response(status_code=204)


def _release_profile_dict(item: ReleaseProfile) -> dict:
    def load(raw, fallback):
        try: return json.loads(raw or "")
        except (json.JSONDecodeError, TypeError): return fallback
    return {
        "id": item.id, "name": item.name, "content_type": item.content_type,
        "required_terms": load(item.required_terms_json, []),
        "ignored_terms": load(item.ignored_terms_json, []),
        "preferred_scores": load(item.preferred_scores_json, {}),
        "indexers": load(item.indexers_json, []), "enabled": item.enabled,
    }


@app.get("/api/release-profiles")
def release_profiles(db: Session = Depends(get_session)):
    items=db.scalars(select(ReleaseProfile).where(ReleaseProfile.content_type.in_(("all","scene"))).order_by(ReleaseProfile.name)).all()
    return [_release_profile_dict(item) for item in items]



def _save_release_profile(db: Session, request: ReleaseProfileWrite, item: ReleaseProfile | None = None):
    if item is None:
        item = ReleaseProfile(name=request.name.strip()); db.add(item)
    item.name = request.name.strip(); item.content_type = request.content_type
    item.required_terms_json = json.dumps(request.required_terms)
    item.ignored_terms_json = json.dumps(request.ignored_terms)
    item.preferred_scores_json = json.dumps(request.preferred_scores)
    item.indexers_json = json.dumps(request.indexers)
    item.enabled = request.enabled
    db.commit(); db.refresh(item); return item


@app.post("/api/release-profiles", status_code=201)
def create_release_profile(request: ReleaseProfileWrite, db: Session = Depends(get_session)):
    if db.scalar(select(ReleaseProfile.id).where(ReleaseProfile.name == request.name.strip())):
        raise HTTPException(409, "Release profile name already exists")
    return _release_profile_dict(_save_release_profile(db, request))


@app.put("/api/release-profiles/{profile_id}")
def update_release_profile(profile_id: int, request: ReleaseProfileWrite, db: Session = Depends(get_session)):
    item = db.get(ReleaseProfile, profile_id)
    if item is None: raise HTTPException(404, "Release profile not found")
    duplicate = db.scalar(select(ReleaseProfile.id).where(ReleaseProfile.name == request.name.strip(), ReleaseProfile.id != profile_id))
    if duplicate: raise HTTPException(409, "Release profile name already exists")
    return _release_profile_dict(_save_release_profile(db, request, item))


@app.delete("/api/release-profiles/{profile_id}", status_code=204)
def delete_release_profile(profile_id: int, db: Session = Depends(get_session)):
    item = db.get(ReleaseProfile, profile_id)
    if item is None: raise HTTPException(404, "Release profile not found")
    db.delete(item); db.commit(); return Response(status_code=204)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "ScarletX", "version": "0.3.10-beta.1", "upstream": "SceneCore 0.7.16"}


@app.get("/api/search/status")
def search_status(settings: Settings = Depends(get_runtime_settings)):
    return {**metadata_provider_status(settings), "categories": ["scenes", "performers", "studios"]}



@app.get("/api/indexers/newznab/status")
def newznab_status(settings: Settings = Depends(get_runtime_settings)):
    indexers = settings.newznab_indexers()
    return {
        "configured": bool(indexers),
        "indexers": [
            {"name": item.name, "enabled": item.enabled,
             "rss_enabled": item.rss_enabled, "priority": item.priority}
            for item in indexers
        ],
    }


@app.post("/api/indexers/{name}/test")
async def test_indexer(name: str, settings: Settings = Depends(get_runtime_settings)):
    indexer = next((item for item in settings.newznab_indexers() if item.name == name), None)
    if indexer is None:
        raise HTTPException(404, "Indexer is not configured")
    try:
        async with NewznabClient(indexer) as client:
            await client.caps()
        return {"ok": True, "name": indexer.name}
    except NewznabError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/search/releases")
async def search_releases(q: str = Query(min_length=2), limit: int = Query(100, ge=1, le=100), settings: Settings = Depends(get_runtime_settings)):
    indexers = [item for item in settings.newznab_indexers() if item.enabled]
    if not indexers:
        raise HTTPException(503, "No enabled Newznab indexers are configured")
    async def search_one(indexer):
        async with NewznabClient(indexer) as nzb:
            return await nzb.search(q, limit, content_type="scene")
    responses = await asyncio.gather(*(search_one(indexer) for indexer in indexers), return_exceptions=True)
    items, errors = [], {}
    for indexer, response in zip(indexers, responses, strict=True):
        if isinstance(response, Exception):
            errors[indexer.name] = str(response) if isinstance(response, NewznabError) else "Search failed"
        else:
            items.extend(item.model_dump(exclude={"download_url"}) for item in response)
    minimum_date = datetime.min.replace(tzinfo=UTC)
    items.sort(key=lambda item: item.get("published_at") or minimum_date, reverse=True)
    return {"items": items, "total": len(items), "errors": errors}



@app.get("/api/download-client/status")
async def download_client_status(settings: Settings = Depends(get_runtime_settings)):
    providers = [item for item in settings.native_usenet_providers() if item.enabled and item.host]
    return {
        "id": "scarletx", "provider": "ScarletX Built-In",
        "configured": bool(providers), "connected": bool(providers), "selected": True,
        "providers": len(providers), "tools": native_tool_status(),
    }


@app.post("/api/download-client/test")
async def test_download_client(settings: Settings = Depends(get_runtime_settings)):
    providers = [item for item in settings.native_usenet_providers() if item.enabled]
    if not providers:
        raise HTTPException(503, "No enabled Usenet provider is configured")
    try:
        return await asyncio.to_thread(test_native_provider, providers[0])
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/download-clients/native/test")
async def test_native_usenet_form_settings(request: UsenetProviderTestWrite, settings: Settings = Depends(get_runtime_settings)):
    current = {(p.name.casefold(), p.host.casefold(), p.port): p for p in settings.native_usenet_providers()}
    match = current.get((request.name.casefold(), request.host.casefold(), request.port))
    password = request.password or (match.password.get_secret_value() if match else "")
    provider = UsenetProviderConfig(
        name=request.name, host=request.host, port=request.port, username=request.username,
        password=SecretStr(password), use_ssl=True, connections=request.connections,
        enabled=request.enabled, priority=request.priority,
    )
    try:
        return await asyncio.to_thread(test_native_provider, provider)
    except Exception as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/download-clients/status")
async def download_clients_status(settings: Settings = Depends(get_runtime_settings)):
    providers = [item for item in settings.native_usenet_providers() if item.enabled and item.host]
    return [{
        "id": "scarletx", "provider": "ScarletX Built-In",
        "configured": bool(providers), "connected": bool(providers), "selected": True,
        "providers": len(providers), "tools": native_tool_status(),
    }]


def _metadata_content_type(identifier: str | None, existing: Scene | None = None) -> str:
    return "scene"



async def _fetch_linked_metadata(settings: Settings, identifier: str, content_type: str) -> RemoteScene:
    async with client(settings) as metadata:
        return await metadata.get_scene(identifier)



async def process_completed_downloads() -> dict:
    with SessionLocal() as db:
        settings = load_database_settings(db)

    def _metadata_factory(_settings):
        return client(settings)

    return await process_downloads_core(SessionLocal, settings, metadata_factory=_metadata_factory)


async def completed_download_import_loop() -> None:
    while True:
        poll_seconds = 30
        try:
            result = await process_completed_downloads()
            poll_seconds = int(result.get("poll_seconds", 30))
        except asyncio.CancelledError:
            raise
        except Exception:
            # A transient download/metadata/database failure must not stop the watcher.
            pass
        await asyncio.sleep(max(10, poll_seconds))


async def automatic_search_loop() -> None:
    while True:
        sleep_seconds = 3600
        try:
            with SessionLocal() as db:
                settings = load_database_settings(db)
                sleep_seconds = max(300, settings.automatic_search_interval_minutes * 60)
            if settings.automatic_search_enabled:
                await automatic_search_cycle(SessionLocal, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Search/indexer outages are retried on the next interval.
            pass
        await asyncio.sleep(sleep_seconds)


async def rss_sync_loop() -> None:
    while True:
        sleep_seconds = 900
        try:
            with SessionLocal() as db:
                settings = load_database_settings(db)
                sleep_seconds = max(300, settings.rss_sync_interval_minutes * 60)
            if settings.rss_sync_enabled:
                await rss_sync_cycle(SessionLocal, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(sleep_seconds)


async def backup_loop() -> None:
    while True:
        sleep_seconds = 3600
        try:
            with SessionLocal() as db:
                settings = load_database_settings(db)
                sleep_seconds = max(3600, settings.backup_interval_hours * 3600)
                if settings.backup_enabled:
                    latest = db.scalar(select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(1))
                    age = (utcnow() - latest.created_at).total_seconds() if latest else None
                    if latest is None or age >= settings.backup_interval_hours * 3600:
                        create_backup(db, settings.backup_directory, settings.backup_keep)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(sleep_seconds)


@app.post("/api/downloads/process")
async def process_downloads_now():
    return await process_completed_downloads()


@app.get("/api/automation/status")
def automation_status(db: Session = Depends(get_session)):
    settings = load_database_settings(db)
    return {
        "enabled": settings.automatic_search_enabled,
        "interval_minutes": settings.automatic_search_interval_minutes,
        "batch_size": settings.automatic_search_batch_size,
        "indexers_configured": len(settings.newznab_indexers()),
        "download_client": "scarletx",
        "native_usenet_configured": native_client_ready(settings),
    }


@app.post("/api/automation/search")
async def run_automatic_search_now(db: Session = Depends(get_session)):
    settings = load_database_settings(db)
    # A manual run intentionally executes even if the scheduler toggle is off.
    return await automatic_search_cycle(SessionLocal, settings.model_copy(update={"automatic_search_enabled": True}))


@app.get("/api/rss/status")
def rss_status(db: Session = Depends(get_session)):
    settings = load_database_settings(db)
    count = db.scalar(select(func.count(IndexerFeedItem.id))) or 0
    latest = db.scalar(select(IndexerFeedItem).order_by(IndexerFeedItem.seen_at.desc()).limit(1))
    return {
        "enabled": settings.rss_sync_enabled,
        "interval_minutes": settings.rss_sync_interval_minutes,
        "seen_releases": count,
        "last_seen_at": latest.seen_at if latest else None,
        "rss_indexers": [item.name for item in settings.newznab_indexers() if item.enabled and item.rss_enabled],
    }


@app.post("/api/rss/sync")
async def run_rss_now(db: Session = Depends(get_session)):
    settings = load_database_settings(db)
    return await rss_sync_cycle(SessionLocal, settings, force=True)


@app.get("/api/rss/history")
def rss_history(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_session)):
    rows = db.scalars(select(IndexerFeedItem).order_by(IndexerFeedItem.seen_at.desc()).limit(limit)).all()
    result = []
    for row in rows:
        scene = db.get(Scene, row.scene_id) if row.scene_id else None
        result.append({
            "id": row.id, "indexer": row.indexer, "guid": row.guid, "title": row.title,
            "published_at": row.published_at, "seen_at": row.seen_at, "action": row.action,
            "scene_id": row.scene_id, "reason": row.reason,
            "content_type": scene.content_type if scene else None,
        })
    return result


@app.get("/api/blocklist")
def blocklist(limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_session)):
    rows = db.scalars(select(ReleaseBlocklist).order_by(ReleaseBlocklist.created_at.desc()).limit(limit)).all()
    result = []
    for x in rows:
        scene = db.get(Scene, x.scene_id) if x.scene_id else None
        result.append({"id": x.id, "indexer": x.indexer, "guid": x.guid, "release_title": x.release_title, "scene_id": x.scene_id, "reason": x.reason, "created_at": x.created_at, "expires_at": x.expires_at, "content_type": scene.content_type if scene else None})
    return result


@app.delete("/api/blocklist/{item_id}", status_code=204)
def unblock_release(item_id: int, db: Session = Depends(get_session)):
    item = db.get(ReleaseBlocklist, item_id)
    if item is None: raise HTTPException(404, "Blocklist entry not found")
    db.delete(item); db.commit(); return Response(status_code=204)


@app.delete("/api/blocklist", status_code=204)
def clear_blocklist(db: Session = Depends(get_session)):
    for item in db.scalars(select(ReleaseBlocklist)).all(): db.delete(item)
    db.commit(); return Response(status_code=204)


def _tracked_download_rows(db: Session, items: list[TrackedDownload]) -> list[dict]:
    if not items: return []
    item_ids=[x.id for x in items]; scene_ids={x.scene_id for x in items if x.scene_id}; external_ids={x.nzo_id for x in items}
    metas={x.tracked_download_id:x for x in db.scalars(select(TrackedDownloadMeta).where(TrackedDownloadMeta.tracked_download_id.in_(item_ids))).all()}
    scenes={x.id:x for x in db.scalars(select(Scene).where(Scene.id.in_(scene_ids))).all()} if scene_ids else {}
    natives={x.id:x for x in db.scalars(select(NativeUsenetJob).where(NativeUsenetJob.id.in_(external_ids))).all()} if external_ids else {}
    rows=[]
    for item in items:
        meta=metas.get(item.id);scene=scenes.get(item.scene_id);client_name=meta.download_client if meta else "scarletx";native=natives.get(item.nzo_id) if client_name=="scarletx" else None
        row={"id":item.id,"external_id":item.nzo_id,"nzo_id":item.nzo_id,"content_type":scene.content_type if scene else None,"release_title":item.scene_title or item.release_title,"release_guid":meta.release_guid if meta else None,"download_client":client_name,"protocol":meta.protocol if meta else "usenet","scene_tpdb_id":item.scene_tpdb_id,"scene_title":item.scene_title,"scene_id":item.scene_id,"status":item.status,"client_status":item.client_status,"storage_path":item.storage_path,"error":item.error,"created_at":item.created_at,"completed_at":item.completed_at,"imported_at":item.imported_at}
        if native:
            nd=native_job_dict(native);row.update({"client_status":native.status,"progress":nd["progress"],"downloaded_bytes":nd["downloaded_bytes"],"total_bytes":nd["total_bytes"],"speed_bps":nd["speed_bps"],"eta_seconds":nd["eta_seconds"],"provider":nd.get("provider"),"provider_stats":nd.get("provider_stats",[]),"active_connections":nd.get("active_connections"),"connection_cap":nd.get("connection_cap"),"phase":nd.get("phase"),"postprocess_note":nd.get("postprocess_note"),"native_job":nd})
        rows.append(row)
    return rows


@app.get("/api/downloads/tracked")
def tracked_downloads(db: Session = Depends(get_session)):
    items=db.scalars(select(TrackedDownload).order_by(TrackedDownload.created_at.desc()).limit(200)).all()
    return _tracked_download_rows(db,items)


@app.get("/api/downloads/queue")
def download_queue(db: Session = Depends(get_session)):
    return {"scarletx": native_queue_rows(db)}

@app.get("/api/downloads/history")
def download_history(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_session)):
    return {"scarletx": native_history_rows(db, limit)}


@app.get("/api/downloads/completed")
def completed_downloads(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_session)):
    rows = native_completed_rows(db, limit)
    ids = [row["id"] for row in rows]
    tracked_by_id = {x.nzo_id:x for x in db.scalars(select(TrackedDownload).where(TrackedDownload.nzo_id.in_(ids))).all()} if ids else {}
    return {"scarletx": [{**row,"scene_title":tracked_by_id[row["id"]].scene_title if row["id"] in tracked_by_id else None,"release_title":tracked_by_id[row["id"]].release_title if row["id"] in tracked_by_id else row.get("title"),"imported_at":tracked_by_id[row["id"]].imported_at if row["id"] in tracked_by_id else None} for row in rows]}


@app.post("/api/downloads/native/{job_id}/reprocess")
async def reprocess_native_download(job_id: str, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    job = _native_job_or_404(db, job_id)
    if job.status != "completed":
        raise HTTPException(409, f"Cannot reprocess a {job.status} job")
    try:
        result = await reprocess_native_completed_job(SessionLocal, settings, job_id)
        # Give the normal completed-import loop a chance immediately rather than
        # waiting for its next poll interval.
        try:
            await process_completed_downloads()
        except Exception:
            pass
        return result
    except NativeUsenetError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/downloads/failed")
def failed_downloads(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_session)):
    return {"scarletx": native_failed_rows(db, limit)}


@app.delete("/api/downloads/failed")
def clear_failed_downloads(db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    jobs = db.scalars(select(NativeUsenetJob).where(NativeUsenetJob.status == "failed")).all()
    incomplete_root = Path(settings.native_usenet_incomplete_dir).expanduser().resolve()
    failed_root = incomplete_root.parent / "failed"
    cleared = 0
    for job in jobs:
        for raw_path in (job.output_path, str(incomplete_root / job.id)):
            if not raw_path:
                continue
            path = Path(raw_path).expanduser()
            try:
                resolved = path.resolve()
                if resolved == failed_root or failed_root in resolved.parents or resolved == incomplete_root or incomplete_root in resolved.parents:
                    if resolved.is_dir():
                        shutil.rmtree(resolved, ignore_errors=True)
                    elif resolved.exists():
                        resolved.unlink(missing_ok=True)
            except Exception:
                pass
        tracked = db.scalar(select(TrackedDownload).where(TrackedDownload.nzo_id == job.id))
        if tracked is not None:
            db.delete(tracked)
        db.delete(job)
        cleared += 1
    db.commit()
    return {"cleared": cleared}


def _native_job_or_404(db: Session, job_id: str) -> NativeUsenetJob:
    job = db.get(NativeUsenetJob, job_id)
    if job is None:
        raise HTTPException(404, "Built-in download job not found")
    return job


@app.post("/api/downloads/native/{job_id}/pause")
def pause_native_download(job_id: str, db: Session = Depends(get_session)):
    job = _native_job_or_404(db, job_id)
    if job.status not in {"queued", "downloading"}:
        raise HTTPException(409, f"Cannot pause a {job.status} job")
    job.status = "paused"
    db.commit()
    return native_job_dict(job)


@app.post("/api/downloads/native/{job_id}/resume")
def resume_native_download(job_id: str, db: Session = Depends(get_session)):
    job = _native_job_or_404(db, job_id)
    if job.status not in {"paused", "failed"}:
        raise HTTPException(409, f"Cannot resume a {job.status} job")
    job.status = "queued"
    job.cancel_requested = False
    job.error = None
    job.completed_at = None
    db.commit()
    return native_job_dict(job)


@app.post("/api/downloads/native/{job_id}/cancel")
def cancel_native_download(job_id: str, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    job = _native_job_or_404(db, job_id)
    if job.status in {"completed", "cancelled"}:
        return native_job_dict(job)
    job.cancel_requested = True
    request_native_cancel(job_id)
    if job.status == "queued":
        job.status = "cancelled"
        job.completed_at = utcnow()
        job.output_path = None
        shutil.rmtree(Path(settings.native_usenet_incomplete_dir).expanduser() / job.id, ignore_errors=True)
    tracked = db.scalar(select(TrackedDownload).where(TrackedDownload.nzo_id == job.id))
    if tracked is not None:
        tracked.status = "cancelled"
        tracked.client_status = "cancelled"
        tracked.error = None
        tracked.completed_at = utcnow()
        tracked.last_checked_at = utcnow()
    db.commit()
    return native_job_dict(job)


@app.post("/api/downloads/native/{job_id}/password")
def set_native_download_password(job_id: str, request: NativeDownloadPasswordWrite, db: Session = Depends(get_session)):
    job = _native_job_or_404(db, job_id)
    job.unpack_password = request.password or None
    db.commit()
    return {"id": job.id, "password_configured": bool(job.unpack_password)}


@app.post("/api/search/releases/grab", status_code=202)
async def grab_release(request: GrabReleaseRequest, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    indexer = next((item for item in settings.newznab_indexers() if item.name == request.indexer and item.enabled), None)
    if indexer is None:
        raise HTTPException(404, "Indexer is not configured or is disabled")
    linked_scene = db.get(Scene, request.library_item_id) if request.library_item_id else None
    if linked_scene is not None and linked_scene.content_type != "scene":
        raise HTTPException(404, "Scene not found")
    try:
        async with NewznabClient(indexer) as nzb:
            releases = await nzb.search(request.query, 100, content_type="scene")
        release = next((item for item in releases if item.guid == request.guid), None)
        if release is None or not release.download_url:
            raise HTTPException(404, "Release could not be resolved on the indexer")
    except NewznabError as exc:
        raise HTTPException(502, str(exc)) from exc
    if linked_scene:
        return (await grab_specific_release(SessionLocal, settings, scene_id=linked_scene.id, release=release, query=request.query)).as_dict()
    try:
        submitted = await submit_release(settings, release, session_factory=SessionLocal, name=request.scene_title or release.title, category=request.category)
    except DownloadClientError as exc:
        raise HTTPException(502, str(exc)) from exc
    for external_id in submitted.ids:
        if db.scalar(select(TrackedDownload).where(TrackedDownload.nzo_id == external_id)) is None:
            tracked = TrackedDownload(
                nzo_id=external_id, release_title=release.title, indexer=release.indexer, query=request.query,
                scene_tpdb_id=request.scene_tpdb_id, scene_title=request.scene_title, status="queued",
            )
            db.add(tracked); db.flush()
            db.add(TrackedDownloadMeta(tracked_download_id=tracked.id, download_client=submitted.client, release_guid=release.guid, protocol="usenet"))
    label = "ScarletX Built-In"
    db.add(History(event_type="release_grabbed", message=f"Queued {request.scene_title or release.title} in {label}"))
    db.commit()
    return {"status": "queued", "title": request.scene_title or release.title, "download_client": submitted.client, "nzo_ids": list(submitted.ids)}


@app.post("/api/library/scenes/{item_id}/search", status_code=202)
async def search_and_grab_library_item(item_id: int, settings: Settings = Depends(get_runtime_settings)):
    return (await search_and_grab_scene(SessionLocal, item_id, settings)).as_dict()



@app.get("/api/search/scenes", response_model=SearchResponse)
async def search_scenes(
    q: str | None = Query(None, min_length=2),
    performer_id: str | None = Query(None, min_length=1),
    site_id: str | None = Query(None, min_length=1),
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=100),
    settings: Settings = Depends(get_runtime_settings),
):
    if not any((q, performer_id, site_id)):
        raise HTTPException(422, "Provide q, performer_id, or site_id")
    try:
        async with client(settings) as tpdb:
            scene_performer_id = performer_id
            if performer_id and not performer_id.isdigit():
                performer = await tpdb.get_performer(performer_id)
                if performer.search_id is None:
                    raise HTTPException(502, "Metadata performer has no searchable ID")
                scene_performer_id = str(performer.search_id)
            scene_site_id = site_id
            if site_id and not site_id.isdigit():
                studio = await tpdb.get_studio(site_id)
                if studio.search_id is None:
                    raise HTTPException(502, "Metadata studio has no searchable ID")
                scene_site_id = str(studio.search_id)
            return await tpdb.search_scenes(q, page, per_page, scene_performer_id, scene_site_id)
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


@app.get("/api/metadata/scenes/{identifier}", response_model=RemoteScene)
async def scene_detail(identifier: str, settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: return await tpdb.get_scene(identifier)
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc










@app.get("/api/search/performers", response_model=PerformerSearchResponse)
async def search_performers(q: str = Query(min_length=2), page: int = Query(1, ge=1), settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: return await tpdb.search_performers(q, page)
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


@app.get("/api/metadata/performers/{identifier}", response_model=RemotePerson)
async def performer_detail(identifier: str, name: str | None = None, settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb:
            try:
                return await tpdb.get_performer(identifier)
            except MetadataProviderError:
                if not name:
                    raise
                results = await tpdb.search_performers(name, per_page=25)
                normalized_name = name.casefold().removeprefix("the ")
                match = next(
                    (item for item in results.items if item.name.casefold().removeprefix("the ") == normalized_name),
                    None,
                )
                if match:
                    return match
                raise
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


def _remote_scene_local_state(db: Session, remote: RemoteScene) -> dict:
    data = remote.model_dump()
    local = db.scalar(select(Scene).where(Scene.tpdb_id == remote.id, Scene.content_type == "scene").limit(1))
    state = "Available"
    if local is not None:
        data["local_id"] = local.id
        data["monitored"] = bool(local.monitored)
        if db.scalar(select(MediaFile.id).where(MediaFile.scene_id == local.id).limit(1)):
            state = "Downloaded"
        else:
            tracked = db.scalar(select(TrackedDownload).where(TrackedDownload.scene_id == local.id).order_by(TrackedDownload.created_at.desc()).limit(1))
            if tracked is not None:
                client_state = (tracked.client_status or tracked.status or "").strip().lower()
                labels = {
                    "queued":"Queued", "downloading":"Downloading", "paused":"Paused",
                    "postprocessing":"Post-processing", "import_pending":"Import pending",
                    "completed":"Downloaded", "imported":"Downloaded", "failed":"Failed",
                    "cancelled":"Cancelled",
                }
                state = labels.get(client_state, client_state.replace("_", " ").title() or "Monitored")
            elif local.monitored:
                state = "Monitored / Searching"
            else:
                state = "In library"
    data["download_status"] = state
    return data


@app.get("/api/metadata/performers/{identifier}/scenes")
async def performer_scenes(
    identifier: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=100),
    settings: Settings = Depends(get_runtime_settings),
    db: Session = Depends(get_session),
):
    try:
        async with client(settings) as tpdb:
            result = await tpdb.get_performer_scenes(identifier, page, per_page)
        return {"items": [_remote_scene_local_state(db, item) for item in result.items], "total": result.total, "page": result.page, "per_page": result.per_page}
    except MetadataProviderError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/artwork/performers/{identifier}")
async def performer_artwork(identifier: str, size: str = Query("full", pattern="^(full|card)$"), db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    try:
        local = db.scalar(select(Performer).where(Performer.tpdb_id == identifier).limit(1))
        if local is None and identifier.isdigit():
            local = db.get(Performer, int(identifier))
        image_url = local.image_url if local else None
        if not image_url:
            async with client(settings) as tpdb:
                performer = await tpdb.get_performer(identifier)
            image_url = performer.image_url
        if not image_url:
            raise HTTPException(404, "Performer artwork not found")
        if size == "card":
            image, media_type = await cached_remote_thumbnail(f"performer:{identifier}", [image_url], (320, 480), contain=True)
        else:
            image, media_type = await cached_remote_image(f"performer:{identifier}", [image_url])
        return Response(content=image, media_type=media_type, headers={"Cache-Control": "public, max-age=604800, immutable"})
    except MetadataProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except RemoteArtworkError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/artwork/scenes/{identifier}")
async def scene_artwork(identifier: str, settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb:
            scene = await tpdb.get_scene(identifier)
        urls = [value for value in (scene.back_image_url, scene.image_url, scene.poster_url) if value]
        if not urls:
            raise HTTPException(404, "Scene artwork not found")
        image, media_type = await cached_remote_image(f"scene:{identifier}", urls)
        return Response(content=image, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})
    except MetadataProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except RemoteArtworkError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/artwork/studios/{identifier}")
async def studio_artwork(identifier: str, size: str = Query("full", pattern="^(full|card)$"), db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    try:
        local = db.scalar(select(Studio).where(Studio.tpdb_id == identifier).limit(1))
        if local is None and identifier.isdigit():
            local = db.get(Studio, int(identifier))
        local_urls = [value for value in ((local.logo_url if local else None), (local.poster_url if local else None)) if value]
        if size == "card" and local_urls:
            image, media_type = await cached_remote_thumbnail(f"studio:{identifier}", local_urls, (400, 175), contain=True)
            return Response(content=image, media_type=media_type, headers={"Cache-Control": "public, max-age=604800, immutable"})
        image = cached_studio_artwork(identifier)
        if image is None:
            urls = local_urls
            if not urls:
                async with client(settings) as tpdb:
                    studio = await tpdb.get_studio(identifier)
                urls = [value for value in (studio.logo_url, studio.poster_url) if value]
            if not urls:
                raise HTTPException(404, "Studio artwork not found")
            image = await download_and_prepare_studio_artwork(urls)
            cache_studio_artwork(identifier, image)
        return Response(
            content=image,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=21600"},
        )
    except MetadataProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except StudioArtworkError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/search/studios", response_model=StudioSearchResponse)
async def search_studios(q: str = Query(min_length=2), page: int = Query(1, ge=1), settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: return await tpdb.search_studios(q, page)
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


@app.get("/api/metadata/studios/{identifier}", response_model=RemoteStudio)
async def studio_detail(identifier: str, settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: return await tpdb.get_studio(identifier)
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


@app.get("/api/metadata/studios/{identifier}/scenes")
async def studio_scenes(
    identifier: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(48, ge=1, le=100),
    settings: Settings = Depends(get_runtime_settings),
    db: Session = Depends(get_session),
):
    """Return TPDB-verified production-studio scenes with ScarletX download state."""
    try:
        async with client(settings) as tpdb:
            studio = await tpdb.get_studio(identifier)
            search_id = studio.search_id
            if search_id is None and identifier.isdigit():
                search_id = int(identifier)
            if search_id is None:
                raise HTTPException(502, "TPDB studio has no searchable ID")
            result = await tpdb.search_scenes(page=page, per_page=per_page, site_id=str(search_id))
        return {"items": [_remote_scene_local_state(db, item) for item in result.items], "total": result.total, "page": result.page, "per_page": result.per_page}
    except MetadataProviderError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/library/scenes/{identifier}", status_code=201)
async def import_scene(identifier: str, request: ImportRequest, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: remote = await tpdb.get_scene(identifier)
        scene = upsert_scene(db, remote, request.monitored)
        ensure_library_config(db, scene); db.commit()
        return {"id": scene.id, "tpdb_id": scene.tpdb_id, "title": scene.title, "monitored": scene.monitored}
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


async def _background_scene_search(scene_id: int, settings: Settings) -> None:
    try:
        result = await search_and_grab_scene(SessionLocal, scene_id, settings)
        with SessionLocal() as db:
            scene = db.get(Scene, scene_id)
            if scene:
                db.add(History(event_type="scene_monitor_search", scene_id=scene_id, message=f"Immediate monitor search for {scene.title}: {result.status}"))
                db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            scene = db.get(Scene, scene_id)
            if scene:
                db.add(History(event_type="scene_monitor_search_failed", scene_id=scene_id, message=f"Immediate monitor search failed for {scene.title}: {exc}"))
                db.commit()


@app.post("/api/metadata/scenes/{identifier}/monitor", status_code=202)
async def monitor_remote_scene(
    identifier: str,
    tasks: BackgroundTasks,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
):
    """Add/monitor one TPDB scene and immediately search/grab it."""
    try:
        async with client(settings) as tpdb:
            remote = await tpdb.get_scene(identifier)
        scene = upsert_scene(db, remote, True, "scene")
        scene.monitored = True
        ensure_library_config(db, scene)
        db.add(History(event_type="scene_monitoring_changed", scene_id=scene.id, message=f"Monitored scene {scene.title}"))
        db.commit()
        tasks.add_task(_background_scene_search, scene.id, settings)
        return {"id": scene.id, "tpdb_id": scene.tpdb_id, "title": scene.title, "monitored": True, "status": "searching"}
    except MetadataProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/library/scenes/{item_id}/monitor", status_code=202)
async def monitor_library_scene(
    item_id: int,
    tasks: BackgroundTasks,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
):
    """Monitor a library scene and immediately search/grab it."""
    scene = db.get(Scene, item_id)
    if scene is None or scene.content_type != "scene":
        raise HTTPException(404, "Scene not found in library")
    scene.monitored = True
    db.add(History(event_type="scene_monitoring_changed", scene_id=scene.id, message=f"Monitored scene {scene.title}"))
    db.commit()
    tasks.add_task(_background_scene_search, scene.id, settings)
    return {"id": scene.id, "tpdb_id": scene.tpdb_id, "title": scene.title, "monitored": True, "status": "searching"}







ENTITY_PAGE_TIMEOUT_SECONDS = 25


async def _all_adult_entity_scenes(
    entity_type: str, identifier: str, settings: Settings
) -> tuple[list[RemoteScene], str | None]:
    """Fetch every TPDB scene credited to one performer or studio."""
    collected: list[RemoteScene] = []
    seen: set[str] = set()
    page = 1
    per_page = 100
    async with client(settings) as tpdb:
        if entity_type == "performer":
            # The performer scenes endpoint accepts the TPDB performer identifier.
            async def fetch(current_page: int):
                return await tpdb.get_performer_scenes(identifier, current_page, per_page)
        elif entity_type == "studio":
            studio = await tpdb.get_studio(identifier)
            search_id = studio.search_id
            if search_id is None and identifier.isdigit():
                search_id = int(identifier)
            if search_id is None:
                raise MetadataProviderError("TPDB studio has no searchable ID")

            async def fetch(current_page: int):
                return await tpdb.search_scenes(page=current_page, per_page=per_page, site_id=str(search_id))
        else:
            raise ValueError("Unsupported Adult entity type")

        warning = None
        while True:
            try:
                response = await asyncio.wait_for(fetch(page), timeout=ENTITY_PAGE_TIMEOUT_SECONDS)
            except TimeoutError:
                warning = f"TPDB page {page} timed out after {ENTITY_PAGE_TIMEOUT_SECONDS} seconds"
                break
            except MetadataProviderError as exc:
                warning = f"TPDB page {page} failed: {exc}"
                break
            new_items = 0
            for remote in response.items:
                if remote.id in seen:
                    continue
                seen.add(remote.id)
                collected.append(remote)
                new_items += 1
            # TPDB total includes creator/tube entries filtered by ScarletX. Keep
            # paging even if an individual page contains only blocked results.
            if page * per_page >= response.total:
                break
            page += 1
            if page > 1000:
                break
    return collected, warning


async def run_adult_entity_monitor_search(job_id: int, entity_type: str, identifier: str, settings: Settings):
    """Import all entity scenes, search every enabled indexer, and queue the best NZBs through the selected download client."""
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()

    try:
        remote_scenes, metadata_warning = await _all_adult_entity_scenes(entity_type, identifier, settings)
        if not remote_scenes and metadata_warning:
            raise MetadataProviderError(metadata_warning)
        scene_ids: list[int] = []
        with SessionLocal() as db:
            for remote in remote_scenes:
                scene = upsert_scene(db, remote, True, "scene")
                ensure_library_config(db, scene)
                scene_ids.append(scene.id)
            db.commit()

        results = []
        for position, scene_id in enumerate(scene_ids, start=1):
            # This path searches every enabled indexer and routes the best acceptable
            # NZB through the selected ScarletX download client. Existing files and
            # active downloads are respected by the normal grab logic.
            result = await search_and_grab_scene(SessionLocal, scene_id, settings)
            results.append(result.as_dict())
            with SessionLocal() as db:
                job = db.get(BackgroundJob, job_id)
                if job:
                    job.payload = json.dumps({
                        "entity_type": entity_type,
                        "identifier": identifier,
                        "scenes_found": len(remote_scenes),
                        "scenes_searched": position,
                        "metadata_warning": metadata_warning,
                    })
                    db.commit()

        counts: dict[str, int] = {}
        for result in results:
            status = result.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job:
                job.payload = json.dumps({
                    "entity_type": entity_type,
                    "identifier": identifier,
                    "scenes_found": len(remote_scenes),
                    "results": counts,
                    "metadata_warning": metadata_warning,
                })
                job.status = "completed"
                job.finished_at = utcnow()
                db.add(History(
                    event_type=f"{entity_type}_monitor_search",
                    message=f"Monitored {entity_type} and searched {len(remote_scenes)} scenes; queued {counts.get('queued', 0)} downloads",
                ))
                db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(exc)[:1000]
                job.finished_at = utcnow()
                db.commit()


def _queue_adult_entity_monitor_search(
    db: Session,
    tasks: BackgroundTasks,
    entity_type: str,
    identifier: str,
    settings: Settings,
) -> int:
    kind = f"{entity_type}_monitor_search"
    for active in db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.kind == kind,
            BackgroundJob.status.in_(("queued", "running")),
        ).order_by(BackgroundJob.created_at.desc())
    ).all():
        try:
            if json.loads(active.payload or "{}").get("identifier") == identifier:
                return active.id
        except (TypeError, json.JSONDecodeError):
            continue
    job = BackgroundJob(
        kind=kind,
        payload=json.dumps({"entity_type": entity_type, "identifier": identifier}),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    tasks.add_task(run_adult_entity_monitor_search, job.id, entity_type, identifier, settings)
    return job.id


@app.post("/api/library/performers/{identifier}", status_code=201)
async def import_performer(identifier: str, request: ImportRequest, tasks: BackgroundTasks, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: remote = await tpdb.get_performer(identifier)
        performer = upsert_performer(db, remote, request.monitored)
        job_id = _queue_adult_entity_monitor_search(db, tasks, "performer", identifier, settings) if request.monitored else None
        return {"id": performer.id, "tpdb_id": performer.tpdb_id, "name": performer.name, "monitored": performer.monitored, "job_id": job_id}
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


@app.post("/api/library/studios/{identifier}", status_code=201)
async def import_studio(identifier: str, request: ImportRequest, tasks: BackgroundTasks, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    try:
        async with client(settings) as tpdb: remote = await tpdb.get_studio(identifier)
        studio = upsert_studio(db, remote, request.monitored)
        job_id = _queue_adult_entity_monitor_search(db, tasks, "studio", identifier, settings) if request.monitored else None
        return {"id": studio.id, "tpdb_id": studio.tpdb_id, "name": studio.name, "monitored": studio.monitored, "job_id": job_id}
    except MetadataProviderError as exc: raise HTTPException(502, str(exc)) from exc


@app.patch("/api/library/performers/{item_id}/monitor")
async def monitor_performer(
    item_id: int,
    request: ImportRequest,
    tasks: BackgroundTasks,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
):
    item = db.get(Performer, item_id)
    if not item or not item.is_library:
        raise HTTPException(404, "Performer not found in library")
    item.monitored = request.monitored
    db.add(History(event_type="performer_monitoring_changed", message=f"{'Monitored' if request.monitored else 'Unmonitored'} performer {item.name}"))
    db.commit()
    job_id = _queue_adult_entity_monitor_search(db, tasks, "performer", item.tpdb_id, settings) if request.monitored else None
    return {"id": item.id, "tpdb_id": item.tpdb_id, "name": item.name, "monitored": item.monitored, "job_id": job_id}


@app.patch("/api/library/studios/{item_id}/monitor")
async def monitor_studio(
    item_id: int,
    request: ImportRequest,
    tasks: BackgroundTasks,
    db: Session = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
):
    item = db.get(Studio, item_id)
    if not item or not item.is_library:
        raise HTTPException(404, "Studio not found in library")
    item.monitored = request.monitored
    db.add(History(event_type="studio_monitoring_changed", message=f"{'Monitored' if request.monitored else 'Unmonitored'} studio {item.name}"))
    db.commit()
    job_id = _queue_adult_entity_monitor_search(db, tasks, "studio", item.tpdb_id, settings) if request.monitored else None
    return {"id": item.id, "tpdb_id": item.tpdb_id, "name": item.name, "monitored": item.monitored, "job_id": job_id}


def _media_library_rows(db: Session, content_type: str = "scene"):
    """Legacy full-library response, implemented with bounded bulk queries instead of N+1 SQL."""
    items = db.scalars(
        select(Scene).where(Scene.content_type == "scene")
        .options(selectinload(Scene.studio), selectinload(Scene.performers), selectinload(Scene.tags))
        .order_by(Scene.imported_at.desc())
    ).unique().all()
    if not items:
        return []
    ids = [item.id for item in items]
    configs = {x.scene_id: x for x in db.scalars(select(LibraryItemConfig).where(LibraryItemConfig.scene_id.in_(ids))).all()}
    default_root = db.scalar(select(RootFolder).where(RootFolder.content_type == "scene").order_by(RootFolder.is_default.desc(), RootFolder.id).limit(1))
    default_profile = db.scalar(select(QualityProfile).where(QualityProfile.content_type.in_(("scene", "all"))).order_by(QualityProfile.is_default.desc(), QualityProfile.id).limit(1))
    missing_configs = []
    for item in items:
        config = configs.get(item.id)
        if config is None:
            config = LibraryItemConfig(scene_id=item.id, root_folder_id=default_root.id if default_root else None, quality_profile_id=default_profile.id if default_profile else None, search_enabled=True)
            db.add(config); configs[item.id] = config; missing_configs.append(config)
        else:
            if config.root_folder_id is None and default_root is not None: config.root_folder_id = default_root.id
            if config.quality_profile_id is None and default_profile is not None: config.quality_profile_id = default_profile.id
    if missing_configs: db.flush()
    root_ids = {x.root_folder_id for x in configs.values() if x.root_folder_id}
    profile_ids = {x.quality_profile_id for x in configs.values() if x.quality_profile_id}
    roots = {x.id: x for x in db.scalars(select(RootFolder).where(RootFolder.id.in_(root_ids))).all()} if root_ids else {}
    profiles = {x.id: x for x in db.scalars(select(QualityProfile).where(QualityProfile.id.in_(profile_ids))).all()} if profile_ids else {}
    media_by_scene = {scene_id: [] for scene_id in ids}
    for f in db.scalars(select(MediaFile).where(MediaFile.scene_id.in_(ids)).order_by(MediaFile.imported_at.desc())).all():
        media_by_scene.setdefault(f.scene_id, []).append(f)
    tag_rows = db.execute(select(library_user_tag.c.scene_id, UserTag).join(UserTag, library_user_tag.c.tag_id == UserTag.id).where(library_user_tag.c.scene_id.in_(ids))).all()
    user_tags_by_scene = {scene_id: [] for scene_id in ids}
    for scene_id, tag in tag_rows: user_tags_by_scene.setdefault(scene_id, []).append(tag)
    rows = []
    for item in items:
        config = configs[item.id]; root = roots.get(config.root_folder_id); profile = profiles.get(config.quality_profile_id); media = media_by_scene.get(item.id, [])
        rows.append({"id":item.id,"tpdb_id":item.tpdb_id,"title":item.title,"release_date":item.release_date,"image_url":item.poster_url or item.image_url,"back_image_url":item.back_image_url,"monitored":item.monitored,"studio":item.studio.name if item.studio else None,"studio_id":item.studio.tpdb_id if item.studio else None,"performers":[{"id":x.tpdb_id,"name":x.name,"image_url":x.image_url} for x in item.performers],"tags":[x.name for x in item.tags],"user_tags":[{"id":x.id,"name":x.name,"label":x.label} for x in user_tags_by_scene.get(item.id, [])],"root_folder":_root_folder_dict(root) if root else None,"quality_profile":_quality_profile_dict(profile) if profile else None,"search_enabled":config.search_enabled,"last_search_at":config.last_search_at,"files":[{"id":f.id,"path":f.path,"size_bytes":f.size_bytes,"quality":f.quality,"release_title":f.release_title} for f in media]})
    db.commit()
    return rows


def _fts_query(value: str | None) -> str | None:
    import re as _re
    tokens = _re.findall(r"[\w]+", (value or "").casefold(), flags=_re.UNICODE)
    return " AND ".join(f'"{token.replace(chr(34), chr(34)*2)}"*' for token in tokens[:12]) or None


def _fts_available(db: Session, table: str) -> bool:
    if engine.url.get_backend_name() != "sqlite":
        return False
    try:
        return bool(db.scalar(text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"), {"name": table}))
    except Exception:
        return False


def _scene_summary_rows(db: Session, *, limit: int, offset: int = 0, q: str | None = None, cursor: str | None = None) -> dict:
    base = [Scene.content_type == "scene"]
    params = {}
    fts = _fts_query(q)
    if fts and _fts_available(db, "scene_search"):
        base.append(text("scenes.id IN (SELECT rowid FROM scene_search WHERE scene_search MATCH :fts_q)"))
        params["fts_q"] = fts
    elif q:
        base.append(Scene.title.ilike(f"%{q.strip()}%"))
    count_stmt = select(func.count(Scene.id)).where(*base)
    total = (db.scalar(count_stmt.params(**params)) or 0) if not cursor and offset == 0 else None
    cursor_parts = _decode_cursor(cursor)
    if cursor_parts:
        try:
            imported = datetime.fromisoformat(str(cursor_parts[0]))
            last_id = int(cursor_parts[1])
        except Exception as exc:
            raise HTTPException(400, "Invalid scene pagination cursor") from exc
        base.append(or_(Scene.imported_at < imported, and_(Scene.imported_at == imported, Scene.id < last_id)))
    stmt = select(Scene).where(*base).options(selectinload(Scene.studio), selectinload(Scene.performers)).order_by(Scene.imported_at.desc(), Scene.id.desc())
    if not cursor:
        stmt = stmt.offset(offset)
    fetched = db.scalars(stmt.limit(limit + 1).params(**params)).unique().all()
    has_more = len(fetched) > limit
    items = fetched[:limit]
    ids = [x.id for x in items]
    file_scene_ids = set(db.scalars(select(MediaFile.scene_id).where(MediaFile.scene_id.in_(ids)).distinct()).all()) if ids else set()
    next_cursor = _encode_cursor(items[-1].imported_at.isoformat(), items[-1].id) if has_more and items else None
    return {"total": int(total) if total is not None else None, "offset": offset if not cursor else None, "limit": limit, "has_more": has_more, "next_cursor": next_cursor, "items": [
        {"id":x.id,"tpdb_id":x.tpdb_id,"title":x.title,"release_date":x.release_date,"image_url":x.poster_url or x.image_url,"monitored":x.monitored,
         "studio":x.studio.name if x.studio else None,"studio_id":x.studio.tpdb_id if x.studio else None,
         "performers":[{"id":p.tpdb_id,"name":p.name,"image_url":p.image_url} for p in x.performers],"has_file":x.id in file_scene_ids}
        for x in items]}


@app.get("/api/library/scenes/page")
def library_scene_page(limit: int = Query(100, ge=1, le=250), offset: int = Query(0, ge=0), cursor: str | None = None, q: str | None = None, db: Session = Depends(get_session)):
    return scene_summary_page(db, limit=limit, offset=offset, q=q, cursor=cursor)


@app.get("/api/library/scenes/{item_id}/detail")
def library_scene_detail(item_id: int, db: Session = Depends(get_session)):
    rows = _media_library_rows_for_ids(db, [item_id])
    if not rows: raise HTTPException(404, "Scene not found")
    return rows[0]


def _media_library_rows_for_ids(db: Session, ids: list[int]) -> list[dict]:
    if not ids: return []
    items = db.scalars(select(Scene).where(Scene.id.in_(ids), Scene.content_type == "scene").options(selectinload(Scene.studio), selectinload(Scene.performers), selectinload(Scene.tags))).unique().all()
    result=[]
    for item in items:
        config=ensure_library_config(db,item);root=db.get(RootFolder,config.root_folder_id) if config.root_folder_id else None;profile=db.get(QualityProfile,config.quality_profile_id) if config.quality_profile_id else None;media=db.scalars(select(MediaFile).where(MediaFile.scene_id==item.id).order_by(MediaFile.imported_at.desc())).all();user_tags=db.execute(select(UserTag).join(library_user_tag,library_user_tag.c.tag_id==UserTag.id).where(library_user_tag.c.scene_id==item.id)).scalars().all()
        result.append({"id":item.id,"tpdb_id":item.tpdb_id,"title":item.title,"description":item.description,"duration":item.duration,"release_date":item.release_date,"image_url":item.poster_url or item.image_url,"back_image_url":item.back_image_url,"monitored":item.monitored,"studio":item.studio.name if item.studio else None,"studio_id":item.studio.tpdb_id if item.studio else None,"performers":[{"id":x.tpdb_id,"name":x.name,"image_url":x.image_url} for x in item.performers],"tags":[x.name for x in item.tags],"user_tags":[{"id":x.id,"name":x.name,"label":x.label} for x in user_tags],"root_folder":_root_folder_dict(root) if root else None,"quality_profile":_quality_profile_dict(profile) if profile else None,"search_enabled":config.search_enabled,"last_search_at":config.last_search_at,"files":[{"id":f.id,"path":f.path,"size_bytes":f.size_bytes,"quality":f.quality,"release_title":f.release_title} for f in media]})
    db.commit(); return result



@app.get("/api/library/scenes")
def library(db: Session = Depends(get_session)):
    return _media_library_rows(db, "scene")




















@app.get("/api/library/scenes/{item_id}/settings")
def library_item_settings(item_id: int, db: Session = Depends(get_session)):
    item=db.get(Scene,item_id)
    if item is None or item.content_type != "scene": raise HTTPException(404,"Scene not found")
    config=ensure_library_config(db,item);db.commit()
    return {"scene_id":item.id,"root_folder_id":config.root_folder_id,"quality_profile_id":config.quality_profile_id,"search_enabled":config.search_enabled}



@app.patch("/api/library/scenes/{item_id}/settings")
def update_library_item_settings(item_id: int, request: LibraryItemSettingsWrite, db: Session = Depends(get_session)):
    item=db.get(Scene,item_id)
    if item is None or item.content_type != "scene": raise HTTPException(404,"Scene not found")
    if request.root_folder_id is not None:
        root=db.get(RootFolder,request.root_folder_id)
        if root is None or root.content_type != "scene": raise HTTPException(422,"Root folder must be a scene root")
    if request.quality_profile_id is not None and db.get(QualityProfile,request.quality_profile_id) is None: raise HTTPException(422,"Quality profile not found")
    config=ensure_library_config(db,item);config.root_folder_id=request.root_folder_id;config.quality_profile_id=request.quality_profile_id;config.search_enabled=request.search_enabled;db.commit()
    return {"scene_id":item.id,"root_folder_id":config.root_folder_id,"quality_profile_id":config.quality_profile_id,"search_enabled":config.search_enabled}




@app.get("/api/tags")
def user_tags(db: Session = Depends(get_session)):
    rows = db.scalars(select(UserTag).order_by(UserTag.name)).all()
    return [{"id": row.id, "name": row.name, "label": row.label} for row in rows]


@app.post("/api/tags", status_code=201)
def create_user_tag(request: UserTagWrite, db: Session = Depends(get_session)):
    name = request.name.strip()
    if db.scalar(select(UserTag.id).where(UserTag.name == name)):
        raise HTTPException(409, "Tag already exists")
    row = UserTag(name=name, label=request.label); db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "label": row.label}


@app.put("/api/tags/{tag_id}")
def update_user_tag(tag_id: int, request: UserTagWrite, db: Session = Depends(get_session)):
    row = db.get(UserTag, tag_id)
    if row is None: raise HTTPException(404, "Tag not found")
    duplicate = db.scalar(select(UserTag.id).where(UserTag.name == request.name.strip(), UserTag.id != tag_id))
    if duplicate: raise HTTPException(409, "Tag already exists")
    row.name = request.name.strip(); row.label = request.label; db.commit(); db.refresh(row)
    return {"id": row.id, "name": row.name, "label": row.label}


@app.delete("/api/tags/{tag_id}", status_code=204)
def delete_user_tag(tag_id: int, db: Session = Depends(get_session)):
    row = db.get(UserTag, tag_id)
    if row is None: raise HTTPException(404, "Tag not found")
    db.delete(row); db.commit(); return Response(status_code=204)


@app.put("/api/library/scenes/{item_id}/tags")
def assign_library_tags(item_id: int, request: LibraryTagsWrite, db: Session = Depends(get_session)):
    scene=db.get(Scene,item_id)
    if scene is None or scene.content_type != "scene": raise HTTPException(404,"Scene not found")
    valid=db.scalars(select(UserTag).where(UserTag.id.in_(request.tag_ids))).all() if request.tag_ids else []
    if len(valid)!=len(set(request.tag_ids)): raise HTTPException(422,"One or more tags do not exist")
    db.execute(library_user_tag.delete().where(library_user_tag.c.scene_id==scene.id))
    for tag in valid: db.execute(library_user_tag.insert().values(scene_id=scene.id,tag_id=tag.id))
    db.commit();return [{"id":tag.id,"name":tag.name,"label":tag.label} for tag in valid]



@app.get("/api/manual-import/scan")
def manual_import_scan(path: str = Query(min_length=1)):
    try: return scan_path_for_manual_import(path)
    except FileImportError as exc: raise HTTPException(422,str(exc)) from exc



@app.post("/api/manual-import", status_code=201)
def manual_import(request: ManualImportWrite, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    scene=db.get(Scene,request.library_item_id)
    if scene is None or scene.content_type != "scene": raise HTTPException(404,"Scene not found")
    source=Path(request.source_path).expanduser()
    try:
        media=import_specific_media_file(db,scene=scene,source=source,release_title=request.release_title or source.stem,settings=settings,import_mode=request.import_mode)
        db.add(History(event_type="manual_import",scene_id=scene.id,message=f"Manually imported {source} -> {media.path}"));db.commit();db.refresh(media)
        return {"id":media.id,"scene_id":media.scene_id,"path":media.path,"quality":media.quality,"release_title":media.release_title}
    except FileImportError as exc: db.rollback();raise HTTPException(422,str(exc)) from exc



@app.post("/api/media-files/{media_id}/rename")
def rename_one_media_file(media_id: int, request: RenameRequest, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "Media file not found")
    try:
        preview = preview_media_rename(db, media, settings)
        old = media.path
        if request.execute:
            old, preview = rename_media_file(db, media, settings)
            db.add(History(event_type="file_renamed", scene_id=media.scene_id, message=f"Renamed {old} -> {preview}"))
            db.commit()
        return {"media_id": media.id, "from": old, "to": preview, "executed": request.execute}
    except FileImportError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/library/scenes/{item_id}/rename")
def rename_library_files(item_id: int, request: RenameRequest, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    scene=db.get(Scene,item_id)
    if scene is None or scene.content_type != "scene": raise HTTPException(404,"Scene not found")
    files=db.scalars(select(MediaFile).where(MediaFile.scene_id==scene.id).order_by(MediaFile.id)).all();rows=[]
    try:
        for media in files:
            old=media.path;target=preview_media_rename(db,media,settings)
            if request.execute: old,target=rename_media_file(db,media,settings);db.add(History(event_type="file_renamed",scene_id=scene.id,message=f"Renamed {old} -> {target}"))
            rows.append({"media_id":media.id,"from":old,"to":target})
        if request.execute:db.commit()
        return {"executed":request.execute,"files":rows}
    except FileImportError as exc:
        if request.execute:db.rollback()
        raise HTTPException(422,str(exc)) from exc



@app.delete("/api/media-files/{media_id}", status_code=200)
def delete_media_file(media_id: int, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "Media file not found")
    scene_id, path = media.scene_id, media.path
    recycled = recycle_media_file(db, media, settings)
    db.add(History(event_type="file_deleted", scene_id=scene_id, message=f"Removed media file {path}" + (f" -> {recycled}" if recycled else "")))
    db.commit()
    return {"deleted": path, "recycled_to": recycled}


@app.post("/api/library/rescan")
def rescan_library(db: Session = Depends(get_session)):
    files = db.scalars(select(MediaFile).order_by(MediaFile.id)).all()
    missing = []
    updated = 0
    for media in files:
        path = Path(media.path)
        if not path.exists():
            missing.append({"media_id": media.id, "scene_id": media.scene_id, "path": media.path})
            continue
        size = path.stat().st_size
        if media.size_bytes != size:
            media.size_bytes = size; updated += 1
    db.commit()
    return {"tracked_files": len(files), "missing_files": missing, "sizes_updated": updated}


@app.get("/api/wanted/missing")
def wanted_missing(limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_session)):
    return missing_items(db, "scene", limit)



@app.get("/api/wanted/cutoff-unmet")
def wanted_cutoff_unmet(limit: int = Query(500, ge=1, le=5000), db: Session = Depends(get_session)):
    return cutoff_unmet(db, "scene", limit)



@app.post("/api/wanted/search", status_code=202)
async def search_wanted(limit: int = Query(25, ge=1, le=100), db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    rows = missing_items(db, "scene", limit)
    results = [(await search_and_grab_scene(SessionLocal, row["library_item_id"], settings)).as_dict() for row in rows]
    return {"checked": len(results), "queued": sum(1 for item in results if item["status"] == "queued"), "results": results}



@app.get("/api/calendar")
def calendar(start: date | None = None, end: date | None = None, limit: int = Query(500, ge=1, le=2000), db: Session = Depends(get_session)):
    today = datetime.now(UTC).date(); start = start or today; end = end or (today + timedelta(days=90))
    if end < start: raise HTTPException(422, "Calendar end must not be before start")
    return calendar_items(db, start, end, limit)



@app.get("/api/system/diskspace")
def system_diskspace(db: Session = Depends(get_session)):
    return disk_space(db)



@app.get("/api/library/performers/page")
def performers_library_page(limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0), cursor: str | None = None, q: str | None = None, db: Session = Depends(get_session)):
    return performer_summary_page(db, limit=limit, offset=offset, cursor=cursor, q=q)


@app.get("/api/library/studios/page")
def studios_library_page(limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0), cursor: str | None = None, q: str | None = None, db: Session = Depends(get_session)):
    return studio_summary_page(db, limit=limit, offset=offset, cursor=cursor, q=q)


@app.get("/api/library/performers/{item_id}/detail")
def performer_library_detail(item_id: int, db: Session = Depends(get_session)):
    x=db.get(Performer,item_id)
    if not x or not x.is_library: raise HTTPException(404,"Performer not found in library")
    return {"id":x.id,"tpdb_id":x.tpdb_id,"name":x.name,"image_url":x.image_url,"bio":x.bio,"aliases":x.aliases,"monitored":x.monitored}


@app.get("/api/library/studios/{item_id}/detail")
def studio_library_detail(item_id: int, db: Session = Depends(get_session)):
    x=db.get(Studio,item_id)
    if not x or not x.is_library: raise HTTPException(404,"Studio not found in library")
    return {"id":x.id,"tpdb_id":x.tpdb_id,"name":x.name,"image_url":x.poster_url or x.logo_url,"url":x.url,"description":x.description,"monitored":x.monitored}


@app.get("/api/library/performers")
def performers_library(db: Session = Depends(get_session)):
    return performers_library_page(limit=200, offset=0, cursor=None, q=None, db=db)["items"]


@app.get("/api/library/studios")
def studios_library(db: Session = Depends(get_session)):
    return studios_library_page(limit=200, offset=0, cursor=None, q=None, db=db)["items"]


def remove_scene_record(db: Session, item_id: int, content_type: str = "scene") -> Response:
    item=db.get(Scene,item_id)
    if not item or item.content_type != "scene": raise HTTPException(404,"Scene not found in library")
    db.execute(update(History).where(History.scene_id==item.id).values(scene_id=None));db.execute(update(IndexerFeedItem).where(IndexerFeedItem.scene_id==item.id).values(scene_id=None));db.execute(update(ReleaseBlocklist).where(ReleaseBlocklist.scene_id==item.id).values(scene_id=None))
    for tracked in db.scalars(select(TrackedDownload).where(TrackedDownload.scene_id==item.id)).all():tracked.scene_id=None
    db.execute(delete(library_user_tag).where(library_user_tag.c.scene_id==item.id));db.execute(delete(MediaFile).where(MediaFile.scene_id==item.id));db.execute(delete(LibraryItemConfig).where(LibraryItemConfig.scene_id==item.id));db.delete(item);db.commit();return Response(status_code=204)



@app.delete("/api/library/scenes/{item_id}", status_code=204)
def remove_scene(item_id: int, db: Session = Depends(get_session)):
    return remove_scene_record(db, item_id, "scene")






@app.delete("/api/library/performers/{item_id}", status_code=204)
def remove_performer(item_id: int, db: Session = Depends(get_session)):
    item = db.get(Performer, item_id)
    if not item or not item.is_library:
        raise HTTPException(404, "Performer not found in library")
    item.is_library = False
    item.monitored = False
    db.commit()
    return Response(status_code=204)


@app.delete("/api/library/studios/{item_id}", status_code=204)
def remove_studio(item_id: int, db: Session = Depends(get_session)):
    item = db.get(Studio, item_id)
    if not item or not item.is_library:
        raise HTTPException(404, "Studio not found in library")
    item.is_library = False
    item.monitored = False
    db.commit()
    return Response(status_code=204)


async def run_refresh(job_id: int, scene_id: int, settings: Settings):
    with SessionLocal() as db:
        job=db.get(BackgroundJob,job_id)
        if job is None:return
        job.status="running";db.commit()
        try:
            scene=db.get(Scene,scene_id)
            if scene is None or scene.content_type != "scene":raise ValueError("Scene no longer exists")
            async with client(settings) as metadata:remote=await metadata.get_scene(scene.tpdb_id)
            upsert_scene(db,remote,scene.monitored,"scene");job=db.get(BackgroundJob,job_id);job.status="completed";job.finished_at=utcnow();db.commit()
        except Exception as exc:
            job=db.get(BackgroundJob,job_id)
            if job:job.status="failed";job.error=str(exc)[:1000];job.finished_at=utcnow();db.commit()



@app.post("/api/library/scenes/{scene_id}/refresh", status_code=202)
def refresh(scene_id: int, tasks: BackgroundTasks, db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    item = db.get(Scene, scene_id)
    if item is None or item.content_type != "scene": raise HTTPException(404, "Scene not found")
    job = BackgroundJob(kind="metadata_refresh", payload=json.dumps({"scene_id": scene_id, "content_type": "scene"})); db.add(job); db.commit(); db.refresh(job)
    tasks.add_task(run_refresh, job.id, scene_id, settings)
    return {"job_id":job.id,"status":job.status}



def _webhook_dict(item: Webhook) -> dict:
    try: events = json.loads(item.events_json or "[]")
    except json.JSONDecodeError: events = []
    try: headers = json.loads(item.headers_json or "{}")
    except json.JSONDecodeError: headers = {}
    return {"id": item.id, "name": item.name, "url": item.url, "events": events, "headers": headers, "secret_configured": bool(item.secret), "enabled": item.enabled}


@app.get("/api/webhooks")
def webhooks(db: Session = Depends(get_session)):
    return [_webhook_dict(item) for item in db.scalars(select(Webhook).order_by(Webhook.name)).all()]


def _save_webhook(db: Session, request: WebhookWrite, item: Webhook | None = None):
    if item is None: item = Webhook(name=request.name, url=request.url); db.add(item)
    item.name = request.name.strip(); item.url = request.url.strip(); item.events_json = json.dumps(request.events)
    item.headers_json = json.dumps(request.headers); item.enabled = request.enabled
    if request.secret is not None: item.secret = request.secret
    db.commit(); db.refresh(item); return item


@app.post("/api/webhooks", status_code=201)
def create_webhook(request: WebhookWrite, db: Session = Depends(get_session)):
    return _webhook_dict(_save_webhook(db, request))


@app.put("/api/webhooks/{webhook_id}")
def update_webhook(webhook_id: int, request: WebhookWrite, db: Session = Depends(get_session)):
    item = db.get(Webhook, webhook_id)
    if item is None: raise HTTPException(404, "Webhook not found")
    return _webhook_dict(_save_webhook(db, request, item))


@app.delete("/api/webhooks/{webhook_id}", status_code=204)
def delete_webhook(webhook_id: int, db: Session = Depends(get_session)):
    item = db.get(Webhook, webhook_id)
    if item is None: raise HTTPException(404, "Webhook not found")
    db.delete(item); db.commit(); return Response(status_code=204)


@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int, db: Session = Depends(get_session)):
    item = db.get(Webhook, webhook_id)
    if item is None: raise HTTPException(404, "Webhook not found")
    original = item.events_json
    try:
        item.events_json = json.dumps(["test"]); db.commit()
        result = await emit_webhooks(SessionLocal, "test", {"message": "ScarletX webhook test", "webhook_id": item.id})
    finally:
        item = db.get(Webhook, webhook_id)
        if item: item.events_json = original; db.commit()
    return result


@app.get("/api/backups")
def backups(db: Session = Depends(get_session)):
    return list_backups(db)


@app.post("/api/backups", status_code=201)
def backup_now(db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    try:
        item = create_backup(db, settings.backup_directory, settings.backup_keep)
        return {"id": item.id, "path": item.path, "size_bytes": item.size_bytes, "created_at": item.created_at}
    except BackupError as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/history")
def application_history(limit: int = Query(200, ge=1, le=5000), event_type: str | None = None, db: Session = Depends(get_session)):
    stmt = select(History)
    if event_type: stmt = stmt.where(History.event_type == event_type)
    rows = db.scalars(stmt.order_by(History.created_at.desc()).limit(limit)).all(); result=[]
    scene_ids={row.scene_id for row in rows if row.scene_id}
    scene_types={item.id:item.content_type for item in db.scalars(select(Scene).where(Scene.id.in_(scene_ids))).all()} if scene_ids else {}
    for row in rows:
        scene_type=scene_types.get(row.scene_id)
        if scene_type is not None and scene_type != "scene": continue
        result.append({"id":row.id,"event_type":row.event_type,"scene_id":row.scene_id,"message":row.message,"created_at":row.created_at,"content_type":"scene" if scene_type else None})
    return result



def _activity_queue_data(db: Session) -> dict:
    active_states = ("queued", "downloading", "paused", "postprocessing", "import_pending")
    native_active = select(NativeUsenetJob.id).where(NativeUsenetJob.status.in_(active_states))
    items = db.scalars(
        select(TrackedDownload).where(
            (TrackedDownload.status.in_(active_states)) |
            (TrackedDownload.client_status.in_(active_states)) |
            (TrackedDownload.nzo_id.in_(native_active))
        ).order_by(TrackedDownload.created_at.asc()).limit(200)
    ).all()
    return {"tracked": _tracked_download_rows(db, items), "clients": {"scarletx": native_queue_rows(db)}}


_ACTIVITY_CACHE_LOCK = threading.Lock()
_ACTIVITY_CACHE: tuple[float, dict] | None = None


def _cached_activity_queue_data(db: Session, max_age: float = 0.65) -> dict:
    """Share one live queue snapshot across polling and SSE clients."""
    global _ACTIVITY_CACHE
    now = time.monotonic()
    with _ACTIVITY_CACHE_LOCK:
        if _ACTIVITY_CACHE and now - _ACTIVITY_CACHE[0] <= max_age:
            return _ACTIVITY_CACHE[1]
        payload = _activity_queue_data(db)
        _ACTIVITY_CACHE = (now, payload)
        return payload


def _load_cached_activity_queue_data() -> dict:
    with SessionLocal() as db:
        return _cached_activity_queue_data(db)


@app.get("/api/activity/queue")
def activity_queue(db: Session = Depends(get_session)):
    return _cached_activity_queue_data(db)


async def _load_activity_stream_snapshot() -> dict:
    return await asyncio.to_thread(_load_cached_activity_queue_data)


@app.get("/api/activity/stream")
async def activity_stream(request: Request):
    raw_last_event_id = request.headers.get("last-event-id")
    try:
        last_event_id = int(raw_last_event_id) if raw_last_event_id is not None else None
    except ValueError:
        last_event_id = None

    async def events():
        subscription = queue_event_broker.subscribe(last_event_id)
        try:
            if last_event_id is None:
                snapshot_id = int(queue_event_broker.snapshot()["last_event_id"])
                payload = await _load_activity_stream_snapshot()
                yield format_sse(QueueEvent(snapshot_id, "snapshot", payload))
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(anext(subscription), timeout=15.0)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if event.kind == "resync":
                    payload = await _load_activity_stream_snapshot()
                    event = QueueEvent(
                        event.id,
                        "resync",
                        {"reason": event.payload.get("reason", "resync"), "snapshot": payload},
                    )
                yield format_sse(event)
        except asyncio.CancelledError:
            raise
        finally:
            await subscription.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

_SYSTEM_STATUS_CACHE: tuple[float, dict] | None = None


@app.get("/api/system/status")
def system_status(db: Session = Depends(get_session)):
    global _SYSTEM_STATUS_CACHE
    now = time.monotonic()
    if _SYSTEM_STATUS_CACHE and now - _SYSTEM_STATUS_CACHE[0] < 2.0:
        return _SYSTEM_STATUS_CACHE[1]
    settings = load_database_settings(db)
    today = datetime.now(UTC).date()
    wanted_count = db.scalar(select(func.count(Scene.id)).where(Scene.content_type=="scene", Scene.monitored.is_(True), ~select(MediaFile.id).where(MediaFile.scene_id==Scene.id).exists())) or 0
    upcoming_count = db.scalar(select(func.count(Scene.id)).where(Scene.content_type=="scene", Scene.monitored.is_(True), Scene.release_date>=today)) or 0
    result = {"version":app.version,"app_name":settings.app_name,"database":engine.url.get_backend_name(),"library":{"scene":db.scalar(select(func.count(Scene.id)).where(Scene.content_type=="scene")) or 0},"performers":db.scalar(select(func.count(Performer.id)).where(Performer.is_library.is_(True))) or 0,"studios":db.scalar(select(func.count(Studio.id)).where(Studio.is_library.is_(True))) or 0,"media_files":db.scalar(select(func.count(MediaFile.id))) or 0,"wanted":int(wanted_count),"upcoming":int(upcoming_count),"tracked_downloads":db.scalar(select(func.count(TrackedDownload.id))) or 0,"native_usenet_jobs":db.scalar(select(func.count(NativeUsenetJob.id))) or 0,"download_client":resolve_client(settings),"rss_seen":db.scalar(select(func.count(IndexerFeedItem.id))) or 0}
    _SYSTEM_STATUS_CACHE = (now, result)
    return result



@app.get("/api/system/health")
async def system_health(db: Session = Depends(get_session), settings: Settings = Depends(get_runtime_settings)):
    checks = []
    try:
        db.execute(select(1)).scalar_one()
        checks.append({"name": "database", "status": "ok"})
    except Exception as exc:
        checks.append({"name": "database", "status": "error", "message": str(exc)})
    for item in disk_space(db):
        if not item.get("exists"):
            checks.append({"name": f"root:{item.get('name')}", "status": "warning", "message": "Root folder does not exist"})
        elif item.get("error"):
            checks.append({"name": f"root:{item.get('name')}", "status": "error", "message": item["error"]})
        else:
            checks.append({"name": f"root:{item.get('name')}", "status": "ok", "free_bytes": item.get("free_bytes")})
    checks.append({"name": "metadata", **metadata_provider_status(settings)})
    client_states = await download_clients_status(settings)
    selected_states = [state for state in client_states if state.get("selected")]
    checks.extend({"name": f"download:{state['provider']}", "status": "ok" if state.get("connected") else ("warning" if not state.get("configured") else "error"), **state} for state in selected_states)
    overall = "error" if any(x.get("status") == "error" for x in checks) else "warning" if any(x.get("status") == "warning" for x in checks) else "ok"
    return {"status": overall, "checks": checks}




def _run_media_scan(job_id: int) -> None:
    try:
        scan_library(SessionLocal, job_id)
    except Exception:
        # scan_library records the failure on the BackgroundJob.
        return


def _run_preview_generation(job_id: int, media_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status = "running"
        db.commit()
        try:
            asset_for(db, media_id, "preview")
            job.status = "completed"
            job.finished_at = utcnow()
            db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:2000]
            job.finished_at = utcnow()
            db.commit()


@app.get("/api/media-library/status")
def media_library_status(db: Session = Depends(get_session)):
    latest = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "media_library_scan").order_by(BackgroundJob.created_at.desc()).limit(1))
    return {
        **library_stats(db),
        "latest_scan": None if latest is None else {
            "id": latest.id, "status": latest.status, "error": latest.error,
            "created_at": latest.created_at, "finished_at": latest.finished_at,
            "result": json.loads(latest.payload) if latest.status == "completed" and latest.payload else None,
        },
    }


@app.post("/api/media-library/scan", status_code=202)
def start_media_library_scan(tasks: BackgroundTasks, db: Session = Depends(get_session)):
    running = db.scalar(select(BackgroundJob).where(BackgroundJob.kind == "media_library_scan", BackgroundJob.status.in_(("queued", "running"))).order_by(BackgroundJob.created_at.desc()).limit(1))
    if running is not None:
        return {"job_id": running.id, "status": running.status, "already_running": True}
    job = BackgroundJob(kind="media_library_scan", payload="{}")
    db.add(job); db.commit(); db.refresh(job)
    tasks.add_task(_run_media_scan, job.id)
    return {"job_id": job.id, "status": job.status, "already_running": False}


@app.get("/api/media-library/files")
def media_library_files(limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_session)):
    # Legacy offset endpoint retained for API compatibility. The UI uses the
    # cursor endpoint below so deep pages remain O(page-size), not O(offset).
    rows = db.scalars(select(MediaFile).order_by(MediaFile.imported_at.desc(), MediaFile.id.desc()).offset(offset).limit(limit)).all()
    return media_rows(db, rows)


@app.get("/api/media-library/files/page")
def media_library_files_page(limit: int = Query(200, ge=1, le=1000), cursor: str | None = Query(None), db: Session = Depends(get_session)):
    stmt = select(MediaFile).order_by(MediaFile.imported_at.desc(), MediaFile.id.desc())
    if cursor:
        parts = _decode_cursor(cursor)
        if len(parts) != 2:
            raise HTTPException(400, "Invalid media cursor")
        try:
            imported_at = datetime.fromisoformat(parts[0])
            media_id = int(parts[1])
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid media cursor") from exc
        stmt = stmt.where(or_(
            MediaFile.imported_at < imported_at,
            and_(MediaFile.imported_at == imported_at, MediaFile.id < media_id),
        ))
    rows = db.scalars(stmt.limit(limit + 1)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1].imported_at.isoformat(), rows[-1].id) if has_more and rows else None
    return {"items": media_rows(db, rows), "has_more": has_more, "next_cursor": next_cursor}


@app.get("/api/media-library/duplicates")
def media_library_duplicates(db: Session = Depends(get_session)):
    return duplicate_rows(db)


@app.get("/api/media-library/unmatched")
def media_library_unmatched(limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), db: Session = Depends(get_session)):
    rows = db.scalars(select(UnmatchedMediaFile).order_by(UnmatchedMediaFile.last_seen_at.desc()).offset(offset).limit(limit)).all()
    return [{"id": x.id, "path": x.path, "display_name": x.display_name, "size_bytes": x.size_bytes, "fingerprint": x.fingerprint, "missing": x.missing, "last_seen_at": x.last_seen_at} for x in rows]


@app.post("/api/media-library/unmatched/{unmatched_id}/match/{scene_id}")
def match_unmatched_media(unmatched_id: int, scene_id: int, db: Session = Depends(get_session)):
    item = db.get(UnmatchedMediaFile, unmatched_id)
    scene = db.get(Scene, scene_id)
    if item is None:
        raise HTTPException(404, "Unmatched file not found")
    if scene is None or scene.content_type != "scene":
        raise HTTPException(404, "Scene not found")
    path = Path(item.path)
    if not path.exists():
        raise HTTPException(409, "Media file is missing")
    media = db.scalar(select(MediaFile).where(MediaFile.path == item.path).limit(1))
    if media is None:
        media = MediaFile(scene_id=scene.id, path=item.path, size_bytes=path.stat().st_size, quality=None, release_title=path.stem)
        db.add(media); db.flush()
    else:
        media.scene_id = scene.id
    db.delete(item)
    try:
        index_media_file(db, media, generate_art=True)
    except MediaLibraryError as exc:
        db.add(History(event_type="media_probe_failed", scene_id=scene.id, message=f"Matched {path.name}, but probe failed: {exc}"))
    db.commit(); db.refresh(media)
    return media_row(db, media)


@app.delete("/api/media-library/missing", status_code=204)
def clear_missing_media(db: Session = Depends(get_session)):
    probes = db.scalars(select(MediaProbe).where(MediaProbe.missing.is_(True))).all()
    for probe in probes:
        media = db.get(MediaFile, probe.media_file_id)
        if media is not None and not Path(media.path).exists():
            db.delete(media)
    unmatched = db.scalars(select(UnmatchedMediaFile).where(UnmatchedMediaFile.missing.is_(True))).all()
    for item in unmatched:
        db.delete(item)
    db.commit()
    return Response(status_code=204)


@app.post("/api/media-files/{media_id}/probe")
def refresh_media_probe(media_id: int, db: Session = Depends(get_session)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "Media file not found")
    try:
        index_media_file(db, media, generate_art=True)
        db.commit()
        return media_row(db, media)
    except MediaLibraryError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/media-files/{media_id}/detail")
def media_file_detail(media_id: int, db: Session = Depends(get_session)):
    media = db.get(MediaFile, media_id)
    if media is None: raise HTTPException(404, "Media file not found")
    return media_row(db, media)


@app.get("/api/media-files/{media_id}/stream")
def stream_media(media_id: int, db: Session = Depends(get_session)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "Media file not found")
    path = Path(media.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "Media file is missing")
    return FileResponse(path, media_type=media_type_for(path), filename=path.name, content_disposition_type="inline", headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"})


@app.get("/api/media-files/{media_id}/thumbnail")
def media_thumbnail(media_id: int, db: Session = Depends(get_session)):
    try:
        path = asset_for(db, media_id, "thumbnail")
        db.commit()
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    except MediaLibraryError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/media-files/{media_id}/screengrab")
def media_screengrab(media_id: int, db: Session = Depends(get_session)):
    try:
        path = asset_for(db, media_id, "screengrab")
        db.commit()
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    except MediaLibraryError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/media-files/{media_id}/preview")
def media_preview(media_id: int, db: Session = Depends(get_session)):
    probe = db.get(MediaProbe, media_id)
    if probe is None or not probe.preview_path or not Path(probe.preview_path).exists():
        raise HTTPException(404, "Preview has not been generated")
    path = Path(probe.preview_path)
    return FileResponse(path, media_type="video/mp4", filename=path.name, content_disposition_type="inline", headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400"})


@app.post("/api/media-files/{media_id}/preview", status_code=202)
def create_media_preview(media_id: int, tasks: BackgroundTasks, db: Session = Depends(get_session)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "Media file not found")
    probe = db.get(MediaProbe, media_id)
    if probe and probe.preview_path and Path(probe.preview_path).exists():
        return {"status": "ready", "media_id": media_id}
    job = BackgroundJob(kind="media_preview", payload=json.dumps({"media_id": media_id}))
    db.add(job); db.commit(); db.refresh(job)
    tasks.add_task(_run_preview_generation, job.id, media_id)
    return {"status": "queued", "job_id": job.id, "media_id": media_id}


@app.patch("/api/media-files/{media_id}/playback")
def set_media_playback(media_id: int, request: PlaybackStateWrite, db: Session = Depends(get_session)):
    media = db.get(MediaFile, media_id)
    if media is None:
        raise HTTPException(404, "Media file not found")
    state = update_playback(db, media_id, position_seconds=request.position_seconds, favorite=request.favorite, played=request.played)
    db.commit()
    return {"media_file_id": media_id, "position_seconds": state.position_seconds, "play_count": state.play_count, "favorite": state.favorite, "last_played_at": state.last_played_at}


@app.get("/api/jobs")
def jobs(db: Session = Depends(get_session)):
    return db.scalars(select(BackgroundJob).order_by(BackgroundJob.created_at.desc()).limit(100)).all()


WEB = Path(__spec__.origin).parent.parent / "web" / "index.html"
@app.get("/", include_in_schema=False)
def web(): return FileResponse(WEB)


# Group the legacy route declarations behind focused APIRouter ownership views.
# Import locally so the relocated legacy implementation does not acquire new E402
# exceptions; route objects stay registered on the original application router.
def _adopt_route_boundaries() -> None:
    from . import automation as automation_routes
    from . import downloads as download_routes
    from . import library as library_routes
    from . import settings as settings_routes

    for route_module in (
        settings_routes,
        library_routes,
        download_routes,
        automation_routes,
    ):
        route_module.adopt_routes(app)


_adopt_route_boundaries()
