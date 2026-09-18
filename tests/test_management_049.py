from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from scarletx.models import BackupRecord, MediaFile, MediaProbe, Scene, UnmatchedMediaFile
from tests.test_incremental_scanner import _database


def test_quiet_hours_cross_midnight_and_timezone():
    from scarletx.download_schedule import DownloadSchedule, schedule_state

    rule = DownloadSchedule(enabled=True, start="22:00", end="07:00", timezone="America/Los_Angeles")
    assert schedule_state(rule, datetime(2026, 9, 18, 5, tzinfo=UTC))["paused"]
    assert schedule_state(rule, datetime(2026, 9, 18, 13, 59, tzinfo=UTC))["paused"]
    assert not schedule_state(rule, datetime(2026, 9, 18, 14, tzinfo=UTC))["paused"]
    # DST fallback: both instances of 01:30 are inside the configured quiet hours.
    assert schedule_state(rule, datetime(2026, 11, 1, 8, 30, tzinfo=UTC))["paused"]
    assert schedule_state(rule, datetime(2026, 11, 1, 9, 30, tzinfo=UTC))["paused"]


def test_schedule_validation_and_speed_cap():
    from scarletx.download_schedule import DownloadSchedule, schedule_state

    for values in [
        dict(start="25:00"),
        dict(timezone="Not/AZone"),
        dict(start="07:00", end="07:00"),
        dict(mode="limit", speed_limit_mb_s=0),
    ]:
        with pytest.raises(ValidationError):
            DownloadSchedule(**values)
    rule = DownloadSchedule(enabled=True, start="09:00", end="17:00", mode="limit", speed_limit_mb_s=4)
    state = schedule_state(rule, datetime(2026, 9, 17, 10, tzinfo=UTC), base_limit=2)
    assert not state["paused"] and state["speed_limit_mb_s"] == 2
    assert schedule_state(rule, datetime(2026, 9, 17, 18, tzinfo=UTC), base_limit=0)["speed_limit_mb_s"] == 0


def test_backup_reminders_missing_overdue_disabled(tmp_path):
    from scarletx.operations import backup_reminder

    engine, factory = _database(tmp_path)
    settings = SimpleNamespace(backup_enabled=True, backup_interval_hours=24)
    now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    with factory() as db:
        assert backup_reminder(db, settings, now)["state"] == "never"
        path = tmp_path / "backup.db"
        path.write_bytes(b"fixture")
        record = BackupRecord(path=str(path), size_bytes=7, created_at=now - timedelta(hours=25))
        db.add(record)
        db.commit()
        assert backup_reminder(db, settings, now)["state"] == "overdue"
        record.created_at = now - timedelta(hours=1)
        db.commit()
        assert backup_reminder(db, settings, now)["state"] == "healthy"
        path.unlink()
        assert backup_reminder(db, settings, now)["state"] == "missing"
        settings.backup_enabled = False
        assert backup_reminder(db, settings, now)["state"] == "disabled"
    engine.dispose()


def test_folder_usage_does_not_follow_symlinks_or_claim_missing_is_empty(tmp_path):
    from scarletx.operations import folder_usage

    data = tmp_path / "data"
    data.mkdir()
    (data / "file").write_bytes(b"1234")
    (data / "loop").symlink_to(data, target_is_directory=True)
    result = folder_usage(data)
    assert result["bytes"] == 4 and result["complete"]
    assert folder_usage(tmp_path / "missing")["bytes"] is None


def test_cleanup_preview_is_bounded_and_read_only(tmp_path):
    from scarletx.operations import cleanup_preview

    engine, factory = _database(tmp_path)
    with factory() as db:
        scene = Scene(tpdb_id="cleanup", title="Cleanup")
        db.add(scene)
        db.flush()
        files = [MediaFile(scene_id=scene.id, path=str(tmp_path / f"{i}.mp4")) for i in range(3)]
        db.add_all(files)
        db.flush()
        db.add_all(
            [
                MediaProbe(media_file_id=files[0].id, fingerprint="same", missing=False),
                MediaProbe(media_file_id=files[1].id, fingerprint="same", missing=False),
                MediaProbe(media_file_id=files[2].id, missing=True),
            ]
        )
        db.add(UnmatchedMediaFile(path=str(tmp_path / "unknown.mp4"), display_name="Unknown"))
        db.commit()
        for category in ["duplicates", "missing", "unmatched"]:
            preview = cleanup_preview(db, category, limit=1, offset=0)
            assert len(preview["items"]) == 1
        assert len(db.scalars(select(MediaFile)).all()) == 3
        assert len(db.scalars(select(UnmatchedMediaFile)).all()) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_schedule_wait_never_resumes_manual_pause(tmp_path, monkeypatch):
    from scarletx.usenet import worker
    from scarletx.models import NativeUsenetJob

    engine, factory = _database(tmp_path)
    with factory() as db:
        db.add(NativeUsenetJob(id="scheduled", title="Scheduled", nzb_url="fixture", status="paused"))
        db.commit()
    polls = []

    async def stop_wait(_):
        polls.append(True)
        raise RuntimeError("stop test")

    monkeypatch.setattr(worker.asyncio, "sleep", stop_wait)
    with pytest.raises(RuntimeError, match="stop test"):
        await worker._wait_if_paused(factory, "scheduled")
    with factory() as db:
        assert db.get(NativeUsenetJob, "scheduled").status == "paused"
    assert polls
    engine.dispose()


@pytest.mark.asyncio
async def test_quiet_hours_automatically_resume_without_state_rewrite(tmp_path, monkeypatch):
    from scarletx.usenet import worker
    from scarletx.models import NativeUsenetJob

    engine, factory = _database(tmp_path)
    with factory() as db:
        db.add(NativeUsenetJob(id="scheduled", title="Scheduled", nzb_url="fixture", status="downloading"))
        db.commit()
    policies = iter([dict(paused=True, speed_limit_mb_s=0), dict(paused=False, speed_limit_mb_s=3)])
    monkeypatch.setattr(worker, "_transfer_policy", lambda *a: next(policies))

    async def no_wait(_):
        return None

    monkeypatch.setattr(worker.asyncio, "sleep", no_wait)
    assert await worker._wait_if_paused(factory, "scheduled") == 3
    with factory() as db:
        assert db.get(NativeUsenetJob, "scheduled").status == "downloading"
    engine.dispose()


def test_scheduled_backup_accepts_sqlite_naive_timestamps(tmp_path, monkeypatch):
    from scarletx import backups

    engine, factory = _database(tmp_path)
    now = datetime(2026, 9, 17, 12, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(backups, "create_backup", lambda *args: calls.append(True))
    with factory() as db:
        db.add(
            BackupRecord(
                path=str(tmp_path / "old.db"),
                size_bytes=1,
                created_at=(now - timedelta(hours=25)).replace(tzinfo=None),
            )
        )
        db.commit()
        settings = SimpleNamespace(
            backup_enabled=True, backup_interval_hours=24, backup_directory=str(tmp_path), backup_keep=7
        )
        assert backups.run_scheduled_backup(db, settings, now)
    assert calls == [True]
    engine.dispose()


def test_schedule_api_persists_and_rejects_bad_times(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from scarletx.db import get_session
    from scarletx.operations_routes import router
    from scarletx.settings_store import load_database_settings

    engine, factory = _database(tmp_path)
    app = FastAPI()
    app.include_router(router)

    def session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = session
    with TestClient(app) as client:
        assert not client.get("/api/operations/download-schedule").json()["rule"]["enabled"]
        response = client.patch(
            "/api/operations/download-schedule",
            json={"enabled": True, "start": "21:00", "end": "06:00", "timezone": "UTC"},
        )
        assert response.status_code == 200
        assert client.patch("/api/operations/download-schedule", json={"start": "bad"}).status_code == 422
        assert client.get("/api/operations/download-schedule").json()["rule"]["start"] == "21:00"
    with factory() as db:
        assert "21:00" in load_database_settings(db).download_schedule_json
    engine.dispose()


@pytest.mark.asyncio
async def test_connection_failure_redacts_provider_error(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from scarletx.operations_routes import test_connection as check
    from scarletx.settings_store import set_setting
    from scarletx.usenet import worker

    engine, factory = _database(tmp_path)
    monkeypatch.setenv("SCARLETX_SECRET_KEY_FILE", str(tmp_path / "secret.key"))

    def fail(_):
        raise RuntimeError("password=private-value")

    monkeypatch.setattr(worker, "test_provider", fail)
    with factory() as db:
        set_setting(db, "native_usenet_enabled", "true")
        set_setting(
            db,
            "native_usenet_providers_json",
            '[{"name":"Example","host":"example.invalid","password":"private-value","enabled":true}]',
        )
        with pytest.raises(HTTPException) as error:
            await check("downloads", db)
        assert error.value.status_code == 502
        assert "private-value" not in error.value.detail
    engine.dispose()


@pytest.mark.asyncio
async def test_indexer_wizard_rejects_http200_api_error(tmp_path, monkeypatch):
    import httpx
    from fastapi import HTTPException
    from scarletx import newznab
    from scarletx.operations_routes import test_connection as check
    from scarletx.settings_store import set_setting

    engine, factory = _database(tmp_path)
    monkeypatch.setenv("SCARLETX_SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    original = newznab.NewznabClient

    class ErrorClient(original):
        def __init__(self, indexer):
            super().__init__(
                indexer,
                transport=httpx.MockTransport(
                    lambda request: httpx.Response(
                        200, text='<error code="100" description="Invalid API key"/>'
                    )
                ),
            )

    monkeypatch.setattr(newznab, "NewznabClient", ErrorClient)
    with factory() as db:
        set_setting(
            db,
            "newznab_indexers_json",
            '[{"name":"Example","url":"https://example.invalid/api","api_key":"fixture","enabled":true}]',
        )
        with pytest.raises(HTTPException) as error:
            await check("indexers", db)
        assert error.value.status_code == 502
    engine.dispose()
