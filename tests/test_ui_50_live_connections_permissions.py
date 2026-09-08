import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from scarletx import config, library_management, status_console


ROOT = Path(__file__).resolve().parents[1]


def test_all_main_library_pages_use_fifty_rows():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text(encoding="utf-8")

    assert "Object.assign(entityPageSize,{scenes:50,performers:50,studios:50})" in index
    assert "const ACTIVITY_QUEUE_PAGE_SIZE=50" in overrides
    assert "const MEDIA_LIBRARY_PAGE_SIZE=50" in overrides


def test_effective_connection_capacity_uses_provider_total_not_global_ceiling(monkeypatch):
    monkeypatch.setattr(config, "_effective_cpu_count", lambda: 12)
    settings = config.Settings(
        native_usenet_providers_json=SecretStr(json.dumps([
            {"name": "Astraweb", "host": "astra.example", "connections": 50, "enabled": True},
            {"name": "Newshosting", "host": "news.example", "connections": 100, "enabled": True},
        ])),
        native_usenet_max_connections=200,
    )

    assert config.effective_native_usenet_connection_capacity(settings) == 150


def test_effective_connection_capacity_still_honors_lower_global_ceiling(monkeypatch):
    monkeypatch.setattr(config, "_effective_cpu_count", lambda: 12)
    settings = config.Settings(
        native_usenet_providers_json=SecretStr(json.dumps([
            {"name": "Astraweb", "host": "astra.example", "connections": 50, "enabled": True},
            {"name": "Newshosting", "host": "news.example", "connections": 100, "enabled": True},
        ])),
        native_usenet_max_connections=80,
    )

    assert config.effective_native_usenet_connection_capacity(settings) == 80


def test_connection_detail_uses_effective_capacity_as_the_top_end():
    assert status_console._connection_detail(
        active_connections=73,
        connection_capacity=150,
    ) == "73 / 150 connections"

    source = (ROOT / "scarletx" / "status_console.py").read_text(encoding="utf-8")
    assert "effective_native_usenet_connection_capacity" in source
    assert "runtime_cap=" not in source


def test_download_page_clamps_stale_runtime_cap_to_provider_capacity():
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text(encoding="utf-8")

    assert "function liveConnectionCapacity(x)" in overrides
    assert "x.provider_stats||[]" in overrides
    assert "x.connection_capacity||x.connection_cap||0" in overrides
    assert "Math.min(providerTotal,reported)" in overrides
    assert "capacity||x.active_connections" in overrides


def test_activity_header_uses_true_count_instead_of_capped_snapshot_length():
    downloads = (ROOT / "scarletx" / "routes" / "downloads.py").read_text(encoding="utf-8")
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text(encoding="utf-8")

    assert '"/api/activity/count"' in downloads
    assert "func.count(TrackedDownload.id)" in downloads
    assert "async function refreshActivityQueueTotal" in overrides
    assert "api('/api/activity/count')" in overrides
    assert "$('#queueBadge').textContent=activityQueueTotal" in overrides
    assert "$('#queueBadge').textContent=rows.length" not in overrides


def test_activity_pages_are_server_paged_beyond_two_hundred_rows():
    downloads = (ROOT / "scarletx" / "routes" / "downloads.py").read_text(encoding="utf-8")
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text(encoding="utf-8")

    assert '"/api/activity/page"' in downloads
    assert ".offset((page - 1) * limit).limit(limit)" in downloads
    assert "async function loadActivityQueuePage" in overrides
    assert "activityQueuePagerHtml(activityQueueTotal)" in overrides


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
