import json
from pathlib import Path

from scarletx.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_install_has_no_preloaded_indexers(monkeypatch):
    monkeypatch.delenv("SCARLETX_NEWZNAB_INDEXERS_JSON", raising=False)
    for key in (
        "SCARLETX_NZBGEEK_API_KEY",
        "SCARLETX_TREASURE_MAPS_API_KEY",
        "SCARLETX_NZBLIFE_API_KEY",
        "SCARLETX_USENET_CRAWLER_API_KEY",
    ):
        monkeypatch.setenv(key, "should-not-preload")
    settings = Settings()
    assert settings.newznab_indexers() == []
    assert settings.newznab_indexers_json.get_secret_value() == "[]"


def test_explicit_indexer_json_is_still_supported(monkeypatch):
    payload = [{"name": "My Indexer", "url": "https://example.invalid/api", "api_key": "key", "enabled": True}]
    monkeypatch.setenv("SCARLETX_NEWZNAB_INDEXERS_JSON", json.dumps(payload))
    settings = Settings()
    assert [row.name for row in settings.newznab_indexers()] == ["My Indexer"]


def test_known_blank_bundled_placeholders_are_hidden_but_real_config_is_kept():
    settings = Settings(newznab_indexers_json=json.dumps([
        {"name": "NZBGeek", "url": "https://api.nzbgeek.info/api", "api_key": "", "enabled": True},
        {"name": "Treasure Maps", "url": "https://treasure-maps.com/api", "api_key": "", "enabled": True},
        {"name": "NZB.life", "url": "https://api.nzb.life", "api_key": "", "enabled": True},
        {"name": "Usenet-Crawler", "url": "https://www.usenet-crawler.com/api", "api_key": "", "enabled": True},
        {"name": "NZBGeek", "url": "https://api.nzbgeek.info/api", "api_key": "configured", "enabled": True},
        {"name": "Custom", "url": "https://custom.invalid/api", "api_key": "", "enabled": True},
    ]))
    rows = settings.newznab_indexers()
    assert [(row.name, row.api_key.get_secret_value()) for row in rows] == [
        ("NZBGeek", "configured"),
        ("Custom", ""),
    ]


def test_approved_exact_logo_assets_are_used_in_shell():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<div class="header-brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6"' in index
    assert '<div class="brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6"' in index
    assert 'href="/scarletx-icon.webp?v=approved-20260918-1"' in index
    assert "scarletx-wordmark.svg" not in index


def test_exact_logo_assets_are_bundled_into_web_image():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "COPY frontend/scarletx-wordmark.webp.b64.00 /tmp/scarletx-wordmark.webp.b64.00" in dockerfile
    assert "COPY frontend/scarletx-icon.svg /usr/share/nginx/html/scarletx-icon.svg" in dockerfile
    assert "COPY frontend/scarletx-icon.webp /usr/share/nginx/html/scarletx-icon.webp" in dockerfile
    assert "a90efeaa68b2f8a96e20d62167582f79ed58ef92aa776e46e8c4d9bad0e3c3ca" in dockerfile
    assert "30f7d52a474ed83d7f6f83d8da8ec9ca3488b6936bced0072dccdf762c10e768" in dockerfile
