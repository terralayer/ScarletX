from pathlib import Path

import pytest

from scarletx import library_management, status_console


ROOT = Path(__file__).resolve().parents[1]


def test_all_main_library_pages_use_fifty_rows():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text(encoding="utf-8")

    assert "Object.assign(entityPageSize,{scenes:50,performers:50,studios:50})" in index
    assert "const ACTIVITY_QUEUE_PAGE_SIZE=50" in overrides
    assert "const MEDIA_LIBRARY_PAGE_SIZE=50" in overrides


def test_connection_detail_reports_live_usage_instead_of_only_runtime_cap():
    assert status_console._connection_detail(
        active_connections=73,
        configured_connections=150,
        runtime_cap=200,
    ) == "73 active | 150 configured | cap 200"

    source = (ROOT / "scarletx" / "status_console.py").read_text(encoding="utf-8")
    assert "native_job_dict" in source
    assert "_connection_detail(" in source
    assert "runtime cap {settings.native_usenet_max_connections}" not in source


def test_unwritable_media_directory_reports_owner_and_mode(tmp_path, monkeypatch):
    target = tmp_path / "Studio"
    target.mkdir()
    monkeypatch.setattr(library_management.os, "access", lambda *_args, **_kwargs: False)

    with pytest.raises(library_management.FileImportError) as caught:
        library_management._require_writable_directory(target)

    detail = str(caught.value)
    assert str(target) in detail
    assert "uid=" in detail
    assert "gid=" in detail
    assert "mode=" in detail


def test_truenas_media_permission_repair_is_recursive():
    template = (
        ROOT / "packaging" / "truenas" / "scarletx" / "templates" / "docker-compose.yaml"
    ).read_text(encoding="utf-8")

    assert 'media_perms_config = {"uid": values.run_as.user, "gid": values.run_as.group, "mode": "always", "recursive": True}' in template
    assert 'perm_container.add_or_skip_action("media", values.storage.media, media_perms_config)' in template
