from __future__ import annotations

import importlib
import importlib.util
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from scarletx.auth import create_session, session_user
from scarletx.db import Base
from scarletx.http_security import _supplied_api_key
from scarletx.models import AuthUser
from scarletx.schemas import AdminCredentialsWrite, AdminSetupWrite

ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_first_run_setup_requires_one_time_token(tmp_path, monkeypatch):
    assert importlib.util.find_spec("scarletx.setup_security") is not None
    module = importlib.import_module("scarletx.setup_security")
    token_file = tmp_path / "setup-token.json"
    monkeypatch.setenv("SCARLETX_SETUP_TOKEN_FILE", str(token_file))
    monkeypatch.delenv("SCARLETX_SETUP_TOKEN", raising=False)
    module = importlib.reload(module)

    token = module.ensure_setup_token(admin_exists=False)
    assert token
    assert token_file.exists()
    assert token not in token_file.read_text(encoding="utf-8")
    assert module.verify_setup_token(token)
    assert not module.verify_setup_token(token + "x")

    module.consume_setup_token()
    assert not token_file.exists()
    assert not module.verify_setup_token(token)


def test_setup_schema_requires_token_but_account_update_does_not():
    setup_fields = AdminSetupWrite.model_fields
    update_fields = AdminCredentialsWrite.model_fields
    assert "setup_token" in setup_fields
    assert setup_fields["setup_token"].is_required()
    assert "setup_token" not in update_fields


def test_query_string_api_keys_are_rejected():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/system/status",
            "headers": [],
            "query_string": b"apikey=should-not-be-accepted",
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("test", 80),
        }
    )
    assert _supplied_api_key(request) == ""


def test_session_lookup_uses_one_select_for_valid_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        user = AuthUser(username="admin", username_normalized="admin", password_hash="x")
        db.add(user)
        db.commit()
        token = create_session(db, user.id, now=datetime.now(UTC))

    selects = []

    @event.listens_for(engine, "before_cursor_execute")
    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    with Session() as db:
        found = session_user(db, token, now=datetime.now(UTC) + timedelta(seconds=1))
        assert found is not None
        assert found.username == "admin"

    assert len(selects) <= 1


def test_secret_store_encrypts_and_decrypts(tmp_path, monkeypatch):
    assert importlib.util.find_spec("scarletx.secret_store") is not None
    monkeypatch.setenv("SCARLETX_SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    module = importlib.import_module("scarletx.secret_store")
    module = importlib.reload(module)

    encrypted = module.encrypt_secret("super-secret")
    assert encrypted.startswith("enc:v1:")
    assert "super-secret" not in encrypted
    assert module.decrypt_secret(encrypted) == "super-secret"
    assert (tmp_path / "secret.key").stat().st_mode & 0o777 == 0o600


def test_settings_store_encrypts_secret_rows_at_rest():
    source = _source("scarletx/settings_store.py")
    assert "encrypt_secret" in source
    assert "decrypt_secret" in source
    assert "migrate_secret" in source


def test_database_backups_preserve_matching_secret_key():
    source = _source("scarletx/backups.py")
    assert "SCARLETX_SECRET_KEY_FILE" in source
    assert "secret_key_path" in source
    assert "0600" in source or "0o600" in source
    assert "with_suffix" in source


def test_archive_member_validation_blocks_traversal():
    assert importlib.util.find_spec("scarletx.archive_security") is not None
    module = importlib.import_module("scarletx.archive_security")

    assert str(module.validate_archive_member_path("folder/video.mkv")) == "folder/video.mkv"
    for unsafe in ("../escape.mkv", "/absolute/file.mkv", "a/../../escape.mkv", "C:/escape.mkv", "C:\\escape.mkv"):
        try:
            module.validate_archive_member_path(unsafe)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe archive path accepted: {unsafe}")


def test_native_extraction_uses_quarantine_and_clears_password():
    source = _source("scarletx/native_usenet.py")
    assert "validate_archive_member_path" in source
    assert "TemporaryDirectory" in source or "mkdtemp" in source
    assert "unpack_password=None" in source or "unpack_password = None" in source


def test_nginx_applies_security_limits_and_compression():
    source = _source("nginx/scarletx.conf")
    for expected in (
        "server_tokens off;",
        "client_max_body_size 100m;",
        "gzip on;",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "X-Frame-Options",
        "Permissions-Policy",
        "Content-Security-Policy",
        "SCARLETX_FORWARDED_PROTO",
    ):
        assert expected in source


def test_backend_container_runs_non_root():
    source = _source("Dockerfile")
    assert "USER 568:568" in source
    assert "SCARLETX_SECRET_KEY_FILE=/config/.scarletx-secret.key" in source
    assert "SCARLETX_SETUP_TOKEN_FILE=/config/setup-token.json" in source


def test_compose_migrates_existing_bind_mount_permissions_before_non_root_backend():
    source = _source("docker-compose.yml")
    assert "scarletx-permissions:" in source
    assert 'user: "0:0"' in source
    assert "chown -R 568:568 /config /downloads /backups" in source
    assert "find /media -type d" in source
    assert "condition: service_completed_successfully" in source


def test_sqlite_pool_and_cache_are_bounded():
    source = _source("scarletx/db.py")
    assert "pool_size=5" in source
    assert "max_overflow=5" in source
    assert "PRAGMA cache_size=-16384" in source


def test_library_matching_uses_prebuilt_index():
    assert importlib.util.find_spec("scarletx.library_match") is not None
    module = importlib.import_module("scarletx.library_match")
    scenes = [
        SimpleNamespace(id=1, title="A Very Specific Scene"),
        SimpleNamespace(id=2, title="Another Completely Different Title"),
    ]
    index = module.build_scene_match_index(scenes)
    assert module.match_local_scene(Path("A.Very.Specific.Scene.1080p.mkv"), index).id == 1
    assert module.match_local_scene(Path("prefix Another Completely Different Title suffix.mp4"), index).id == 2

    media_source = _source("scarletx/media_library.py")
    assert "build_scene_match_index" in media_source
    assert "probe_map" in media_source


def test_completed_download_state_loading_is_batched():
    source = _source("scarletx/download_processing.py")
    assert "TrackedDownloadMeta.tracked_download_id.in_(" in source
    assert "NativeUsenetJob.id.in_(" in source
    assert "metadata_by_tracked" in source
    assert "native_by_id" in source


def test_ci_audits_dependencies_and_dependabot_tracks_supply_chain():
    tests_workflow = _source(".github/workflows/tests.yml")
    assert "pip-audit" in tests_workflow
    dependabot = _source(".github/dependabot.yml")
    assert 'package-ecosystem: "pip"' in dependabot
    assert 'package-ecosystem: "docker"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot


def test_forwarded_proto_is_explicit_in_deployments():
    for path in (
        "docker-compose.yml",
        "docker-compose.truenas.yml",
        "packaging/truenas/scarletx/templates/docker-compose.yaml",
    ):
        assert "SCARLETX_FORWARDED_PROTO" in _source(path)