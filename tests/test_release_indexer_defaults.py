import json
from pathlib import Path

from scarletx.config import _default_indexers


BUNDLED_INDEXER_IDENTIFIERS = (
    "NZBGeek",
    "api.nzbgeek.info",
    "Treasure Maps",
    "treasure-maps.com",
    "NZB.life",
    "api.nzb.life",
    "Usenet-Crawler",
    "usenet-crawler.com",
    "SCARLETX_NZBGEEK_API_KEY",
    "SCARLETX_TREASURE_MAPS_API_KEY",
    "SCARLETX_NZBLIFE_API_KEY",
    "SCARLETX_USENET_CRAWLER_API_KEY",
)


def test_release_build_has_no_bundled_indexer_catalog(monkeypatch):
    monkeypatch.delenv("SCARLETX_NEWZNAB_INDEXERS_JSON", raising=False)
    assert json.loads(_default_indexers()) == []

    source = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in ("scarletx/config.py", "scarletx/settings_store.py")
    )
    for identifier in BUNDLED_INDEXER_IDENTIFIERS:
        assert identifier not in source


def test_explicit_newznab_configuration_is_still_supported(monkeypatch):
    configured = [
        {
            "name": "User Configured Indexer",
            "url": "https://indexer.example/api",
            "api_key": "test-key",
            "adult_categories": [6000],
            "enabled": True,
            "rss_enabled": False,
            "priority": 1,
        }
    ]
    monkeypatch.setenv("SCARLETX_NEWZNAB_INDEXERS_JSON", json.dumps(configured))
    assert json.loads(_default_indexers()) == configured
