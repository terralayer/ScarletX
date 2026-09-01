from __future__ import annotations

import os
from pathlib import Path

from scarletx.status_console import (
    StatusGroup,
    StatusRow,
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


def test_dashboard_never_echoes_secret_like_detail_values():
    groups = [
        StatusGroup("SECURITY", [
            StatusRow("Secrets At Rest", "ENCRYPTED", "configured", "ok"),
        ])
    ]
    rendered = render_dashboard(groups, version="0.3.9", color=False)
    assert "password=" not in rendered.casefold()
    assert "api_key=" not in rendered.casefold()
    assert "setup token" not in rendered.casefold()


def test_main_and_pyproject_remain_at_released_039_version():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    main_source = (root / "scarletx" / "main.py").read_text()
    assert 'version = "0.3.9"' in pyproject
    assert 'version="0.3.9"' in main_source
