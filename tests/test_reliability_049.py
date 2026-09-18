import asyncio
import errno
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from scarletx import backups
from scarletx.models import BackgroundJob, MediaFile, MediaProbe, NativeUsenetJob, Scene, UnmatchedMediaFile
from tests.test_incremental_scanner import _database


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES, errno.EROFS])
def test_backup_directory_failure_is_actionable(tmp_path, monkeypatch, code):
    engine, factory = _database(tmp_path)
    monkeypatch.setattr(backups, "engine", engine)

    def fail(_directory):
        raise OSError(code, "storage unavailable")

    monkeypatch.setattr(backups, "_backup_dir", fail)
    with factory() as db, pytest.raises(backups.BackupError, match="backup"):
        backups.create_backup(db, str(tmp_path / "backups"))
    engine.dispose()


def test_unavailable_scan_root_preserves_presence(tmp_path, monkeypatch):
    from scarletx.media_library import scan_library

    engine, factory = _database(tmp_path)
    root = tmp_path / "unavailable"
    with factory() as db:
        scene = Scene(tpdb_id="presence", title="Presence")
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path=str(root / "video.mp4"))
        unmatched = UnmatchedMediaFile(path=str(root / "unknown.mp4"), display_name="Unknown", missing=False)
        db.add_all([media, unmatched])
        db.flush()
        db.add(MediaProbe(media_file_id=media.id, missing=False))
        db.commit()
        media_id, unmatched_id = media.id, unmatched.id
    result = scan_library(factory, directories=[root])
    assert result["errors"] == 1
    assert result["missing"] == 0
    with factory() as db:
        assert not db.get(MediaProbe, media_id).missing
        assert not db.get(UnmatchedMediaFile, unmatched_id).missing
    engine.dispose()


@pytest.mark.asyncio
async def test_recovery_rejects_malformed_payloads(tmp_path, monkeypatch):
    from scarletx.routes import application

    engine, factory = _database(tmp_path)
    monkeypatch.setattr(application, "SessionLocal", factory)
    with factory() as db:
        db.add_all(
            [
                BackgroundJob(kind="performer_metadata_hydration", status="running", payload=p)
                for p in ["[]", "{}", "invalid"]
            ]
        )
        db.commit()
    tasks = await application.resume_background_jobs(SimpleNamespace())
    assert tasks == []
    with factory() as db:
        rows = db.scalars(select(BackgroundJob)).all()
        assert all(row.status == "failed" and row.error for row in rows)
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EACCES, errno.EROFS])
async def test_download_directory_failure_keeps_retryable_state(tmp_path, monkeypatch, code):
    from scarletx.usenet import worker

    engine, factory = _database(tmp_path)
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id="storage",
                title="Storage",
                nzb_url="https://example.invalid/file",
                status="queued",
                downloaded_bytes=123,
            )
        )
        db.commit()
    settings = SimpleNamespace(
        native_usenet_incomplete_dir=str(tmp_path / "incomplete"),
        native_usenet_complete_dir=str(tmp_path / "complete"),
        native_usenet_providers=lambda: [SimpleNamespace(enabled=True, host="example.invalid")],
    )
    original = Path.mkdir

    def fail(path, *args, **kwargs):
        if "incomplete" in path.parts:
            raise OSError(code, "storage unavailable", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail)
    await worker.process_job(factory, settings, "storage")
    with factory() as db:
        job = db.get(NativeUsenetJob, "storage")
        assert job.status == "failed"
        assert "storage" in job.error.lower()
        assert job.downloaded_bytes == 123
    engine.dispose()


@pytest.mark.asyncio
async def test_scan_recovery_schedules_interrupted_job(tmp_path, monkeypatch):
    from scarletx.routes import application

    engine, factory = _database(tmp_path)
    monkeypatch.setattr(application, "SessionLocal", factory)
    called = []

    async def scan(job_id):
        called.append(job_id)

    monkeypatch.setattr(application, "_run_media_scan", scan)
    with factory() as db:
        job = BackgroundJob(kind="media_library_scan", status="running", payload="{}")
        db.add(job)
        db.commit()
        job_id = job.id
    tasks = await application.resume_background_jobs(SimpleNamespace())
    await asyncio.gather(*tasks)
    assert called == [job_id]
    engine.dispose()


def test_backup_restores_library_settings_auth_and_encrypted_key(tmp_path, monkeypatch):
    import shutil
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from scarletx.auth import hash_password, verify_password, create_session, session_user
    from scarletx.models import AuthUser
    from scarletx.settings_store import set_setting, load_database_settings
    from scarletx.secret_store import SecretStoreError

    engine, factory = _database(tmp_path)
    monkeypatch.setattr(backups, "engine", engine)
    source_key = tmp_path / "original.key"
    monkeypatch.setenv("SCARLETX_SECRET_KEY_FILE", str(source_key))
    with factory() as db:
        user = AuthUser(
            username="restore-admin",
            username_normalized="restore-admin",
            password_hash=hash_password("restore-test-password"),
        )
        db.add(user)
        db.flush()
        token = create_session(db, user.id)
        db.add(Scene(tpdb_id="restored", title="Preserved library"))
        set_setting(db, "app_name", "Restored name")
        set_setting(db, "api_key", "restore-test-api-key")
        db.commit()
        record = backups.create_backup(db, str(tmp_path / "backups"))
        saved = Path(record.path)
        assert saved.with_suffix(".secret.key").stat().st_mode & 0o777 == 0o600
    restored_path = tmp_path / "restored.db"
    shutil.copy2(saved, restored_path)
    restored_key = tmp_path / "restored.key"
    monkeypatch.setenv("SCARLETX_SECRET_KEY_FILE", str(restored_key))
    restored_engine = create_engine(f"sqlite:///{restored_path}")
    with Session(restored_engine) as db:
        with pytest.raises(SecretStoreError):
            load_database_settings(db, force=True)
        shutil.copy2(saved.with_suffix(".secret.key"), restored_key)
        settings = load_database_settings(db, force=True)
        assert settings.app_name == "Restored name"
        assert settings.api_key.get_secret_value() == "restore-test-api-key"
        user = db.scalar(select(AuthUser))
        assert verify_password("restore-test-password", user.password_hash)
        assert session_user(db, token).id == user.id
        assert db.scalar(select(Scene.title)) == "Preserved library"
    restored_engine.dispose()
    engine.dispose()


@pytest.mark.asyncio
async def test_storage_failure_preserves_previous_retry_directory(tmp_path, monkeypatch):
    from scarletx.usenet import worker

    engine, factory = _database(tmp_path)
    prior = tmp_path / "failed" / "saved-download"
    prior.mkdir(parents=True)
    (prior / "partial.bin").write_bytes(b"preserved")
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id="retry",
                title="Retry",
                nzb_url="https://example.invalid/file",
                status="queued",
                output_path=str(prior),
                downloaded_bytes=9,
            )
        )
        db.commit()
    settings = SimpleNamespace(
        native_usenet_incomplete_dir=str(tmp_path / "incomplete"),
        native_usenet_complete_dir=str(tmp_path / "complete"),
        native_usenet_providers=lambda: [SimpleNamespace(enabled=True, host="example.invalid")],
    )
    original = Path.mkdir

    def fail(path, *args, **kwargs):
        if path.name == "incomplete":
            raise OSError(errno.ENOSPC, "No space left", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail)
    await worker.process_job(factory, settings, "retry")
    with factory() as db:
        assert db.get(NativeUsenetJob, "retry").output_path == str(prior)
    assert (prior / "partial.bin").read_bytes() == b"preserved"
    engine.dispose()


def test_backup_cleanup_preserves_original_failure(tmp_path, monkeypatch):
    engine, factory = _database(tmp_path)
    monkeypatch.setattr(backups, "engine", engine)

    def fail_copy(_path):
        raise backups.BackupError("Original backup failure")

    def fail_unlink(_path, **kwargs):
        raise PermissionError("Cleanup denied")

    monkeypatch.setattr(backups, "_copy_secret_key_for_backup", fail_copy)
    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with factory() as db, pytest.raises(backups.BackupError, match="Original backup failure"):
        backups.create_backup(db, str(tmp_path / "backups"))
    engine.dispose()
