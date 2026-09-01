from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.config import Settings
from scarletx.db import Base
from scarletx.models import NativeUsenetJob, Performer, RootFolder, Scene, Studio
from scarletx.status_console import (
    StatusGroup,
    StatusRow,
    collect_startup_status,
    emit_status,
    render_dashboard,
    sanitize_console_text,
)


def sample_groups() -> list[StatusGroup]:
    return [
        StatusGroup("SYSTEM", [
            StatusRow("FastAPI Backend", "ONLINE", ":8000", "ok"),
            StatusRow("Database", "READY", "SQLite", "ok"),
        ]),
        StatusGroup("METADATA", [StatusRow("ThePornDB", "READY", "configured", "ok")]),
        StatusGroup("SEARCH", [StatusRow("Indexers", "ACTIVE", "2 / 2 enabled", "active")]),
        StatusGroup("USENET", [StatusRow("Native Downloader", "READY", "40 connections", "ok")]),
        StatusGroup("POST-PROCESSING", [StatusRow("PAR2", "READY", "par2", "ok")]),
        StatusGroup("LIBRARY", [StatusRow("Library Scanner", "READY", "indexed", "ok")]),
        StatusGroup("STORAGE", [StatusRow("Configuration", "WRITABLE", "/config", "ok")]),
        StatusGroup("SECURITY", [StatusRow("Container User", "NON-ROOT", "UID 568", "ok")]),
    ]


def test_dashboard_contains_wordmark_version_and_all_required_groups():
    rendered = render_dashboard(sample_groups(), version="0.3.9", color=False)
    assert "SCARLETX" in rendered
    assert "TerraLayer Software" in rendered
    assert "ScarletX 0.3.9" in rendered
    for heading in (
        "SYSTEM", "METADATA", "SEARCH", "USENET", "POST-PROCESSING",
        "LIBRARY", "STORAGE", "SECURITY",
    ):
        assert heading in rendered
    assert "ALL SYSTEMS OPERATIONAL" in rendered


def test_dashboard_has_no_ansi_when_color_is_disabled():
    rendered = render_dashboard(sample_groups(), version="0.3.9", color=False)
    assert "\x1b[" not in rendered


def test_dashboard_uses_ansi_when_color_is_enabled():
    rendered = render_dashboard(sample_groups(), version="0.3.9", color=True)
    assert "\x1b[" in rendered


def test_status_symbols_cover_ok_active_warning_and_error():
    rows = [
        StatusRow("Healthy", "READY", "", "ok"),
        StatusRow("Working", "ACTIVE", "", "active"),
        StatusRow("Slow", "DEGRADED", "", "warning"),
        StatusRow("Broken", "FAILED", "", "error"),
    ]
    rendered = render_dashboard([StatusGroup("SYSTEM", rows)], version="0.3.9", color=False)
    assert "[✓]" in rendered
    assert "[●]" in rendered
    assert "[!]" in rendered
    assert "[✗]" in rendered
    assert "DEGRADED" in rendered
    assert "FAILED" in rendered


def test_sanitize_console_text_removes_control_characters_and_newlines():
    value = sanitize_console_text("evil\n[✗] forged\r\t\x00value")
    assert "\n" not in value
    assert "\r" not in value
    assert "\t" not in value
    assert "\x00" not in value
    assert "forged" in value


def test_emit_status_formats_one_safe_aligned_line(capsys):
    emit_status("Astraweb\nforged", "CONNECTED", "TLS\r\nready", severity="ok", color=False)
    output = capsys.readouterr().out.strip()
    assert output.startswith("[✓] Astraweb forged")
    assert "CONNECTED" in output
    assert "TLS ready" in output
    assert "\n" not in output
    assert "\x1b[" not in output


def test_startup_snapshot_reports_real_groups_counts_paths_and_never_secrets(tmp_path, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    media_root = tmp_path / "media"
    incomplete = tmp_path / "incomplete"
    complete = tmp_path / "complete"
    backups = tmp_path / "backups"
    for path in (media_root, incomplete, complete, backups):
        path.mkdir()

    settings = Settings(
        theporndb_api_key="tpdb-super-secret",
        newznab_indexers_json=json.dumps([
            {"name": "One", "url": "https://indexer.example/api", "api_key": "indexer-super-secret", "enabled": True},
            {"name": "Two", "url": "https://indexer2.example/api", "api_key": "another-secret", "enabled": False},
        ]),
        native_usenet_enabled=True,
        native_usenet_providers_json=json.dumps([
            {"name": "Astraweb", "host": "news.example", "port": 563, "username": "user", "password": "usenet-super-secret", "use_ssl": True, "connections": 8, "enabled": True},
        ]),
        native_usenet_incomplete_dir=str(incomplete),
        native_usenet_complete_dir=str(complete),
        backup_directory=str(backups),
        automatic_search_enabled=True,
    )
    monkeypatch.setenv("SCARLETX_SECRET_KEY_FILE", str(tmp_path / ".scarletx-secret.key"))
    monkeypatch.setenv("SCARLETX_CONFIG_DIR", str(tmp_path / "config"))

    with Session() as db:
        db.add_all([
            Scene(tpdb_id="s1", title="Scene One", monitored=True),
            Performer(tpdb_id="p1", name="Performer One", is_library=True),
            Studio(tpdb_id="st1", name="Studio One", is_library=True),
            RootFolder(name="Scenes", content_type="scene", path=str(media_root), is_default=True),
            NativeUsenetJob(id="job1", title="Failed Job", nzb_url="https://example.invalid/x.nzb", status="failed"),
        ])
        db.commit()
        groups = collect_startup_status(db, settings)

    rendered = render_dashboard(groups, version="0.3.9", color=False)
    for heading in ("SYSTEM", "METADATA", "SEARCH", "USENET", "POST-PROCESSING", "LIBRARY", "STORAGE", "SECURITY"):
        assert heading in rendered
    assert "1 scenes" in rendered
    assert "1 performers" in rendered
    assert "1 studios" in rendered
    assert "1 / 2 enabled" in rendered
    assert "Astraweb" in rendered
    assert "TLS :563" in rendered
    assert "1 failed" in rendered
    assert str(media_root) in rendered
    assert "tpdb-super-secret" not in rendered
    assert "indexer-super-secret" not in rendered
    assert "another-secret" not in rendered
    assert "usenet-super-secret" not in rendered


def test_startup_snapshot_degrades_missing_paths_without_raising(tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    missing = tmp_path / "does-not-exist"
    settings = Settings(
        native_usenet_incomplete_dir=str(missing / "incomplete"),
        native_usenet_complete_dir=str(missing / "complete"),
        backup_directory=str(missing / "backups"),
    )
    with Session() as db:
        groups = collect_startup_status(db, settings)
    rendered = render_dashboard(groups, version="0.3.9", color=False)
    assert "MISSING" in rendered or "WARNING" in rendered or "DEGRADED" in rendered


def test_dashboard_never_echoes_secret_like_detail_values():
    groups = [StatusGroup("SECURITY", [StatusRow("Secrets At Rest", "ENCRYPTED", "configured", "ok")])]
    rendered = render_dashboard(groups, version="0.3.9", color=False)
    assert "password=" not in rendered.casefold()
    assert "api_key=" not in rendered.casefold()
    assert "setup token" not in rendered.casefold()


def test_lifespan_wires_startup_dashboard_and_worker_lifecycle_events():
    root = Path(__file__).resolve().parents[1]
    main_source = (root / "scarletx" / "main.py").read_text()
    assert "collect_startup_status" in main_source
    assert "render_dashboard" in main_source
    assert 'emit_status("Background Workers", "ACTIVE"' in main_source
    assert 'emit_status("Background Workers", "STOPPED"' in main_source


def test_core_workers_emit_structured_live_status_events():
    root = Path(__file__).resolve().parents[1] / "scarletx"
    native = (root / "native_usenet.py").read_text()
    imports = (root / "download_processing.py").read_text()
    backups = (root / "backups.py").read_text()
    library = (root / "media_library.py").read_text()

    for source in (native, imports, backups, library):
        assert "from .status_console import emit_status" in source

    assert 'emit_status(provider.name, "CONNECTING"' in native
    assert 'emit_status(provider.name, "CONNECTED"' in native
    assert 'emit_status(provider.name, "FAILED"' in native
    assert 'emit_status("Native Downloader", "ACTIVE"' in native

    assert 'emit_status("Import", "PROCESSING"' in imports
    assert 'emit_status("Import", "COMPLETED"' in imports
    assert 'emit_status("Import", "FAILED"' in imports

    assert 'emit_status("Backup", "PROCESSING"' in backups
    assert 'emit_status("Backup", "COMPLETED"' in backups
    assert 'emit_status("Backup", "FAILED"' in backups

    assert 'emit_status("Library Scan", "ACTIVE"' in library
    assert 'emit_status(\n        "Library Scan",\n        "COMPLETED"' in library
    assert 'emit_status("Library Scan", "FAILED"' in library


def test_main_and_pyproject_remain_at_released_039_version():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    main_source = (root / "scarletx" / "main.py").read_text()
    assert 'version = "0.3.9"' in pyproject
    assert 'version="0.3.9"' in main_source
