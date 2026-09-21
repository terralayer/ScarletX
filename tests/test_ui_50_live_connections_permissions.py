import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from scarletx import config, library_management, status_console


ROOT = Path(__file__).resolve().parents[1]


def test_all_main_library_pages_default_to_twenty_five_rows_with_user_choices():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text(encoding="utf-8")

    assert "Object.assign(entityPageSize,{scenes:50,performers:50,studios:50})" not in index
    assert "entityPageSize={scenes:25,performers:25,studios:25}" in app
    assert 'id="entityPageSize"' in app
    assert "let ACTIVITY_QUEUE_PAGE_SIZE=25" in app
    assert "ACTIVITY_QUEUE_PAGE_SIZE=25" not in overrides
    assert "const MEDIA_LIBRARY_PAGE_SIZE=50" in overrides


def test_scene_library_refresh_uses_one_controlled_batch_job():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    routes = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")

    assert "api('/api/library/scenes/refresh',post())" in app
    assert "let rows=await api('/api/library/scenes');for(let x of rows)" not in app
    assert '@app.post("/api/library/scenes/refresh", status_code=202)' in routes
    assert "metadata_refresh_batch" in routes


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


def test_activity_snapshot_is_not_capped_at_two_hundred_rows():
    application = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    queue_loader = application[application.index("def _activity_queue_data"):application.index("_ACTIVITY_CACHE_LOCK")]

    assert ".limit(200)" not in queue_loader


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


def test_truenas_media_permissions_do_not_unconditionally_rewrite_dataset():
    template = (
        ROOT / "packaging" / "truenas" / "scarletx" / "templates" / "docker-compose.yaml"
    ).read_text(encoding="utf-8")

    assert '"mode": "always"' not in template
    assert 'perm_container.add_or_skip_action("media", values.storage.media, perms_config)' in template
