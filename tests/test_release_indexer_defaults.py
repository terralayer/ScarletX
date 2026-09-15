import json

from scarletx.config import _default_indexers


def test_release_build_has_no_prepopulated_indexers(monkeypatch):
    monkeypatch.delenv("SCARLETX_NEWZNAB_INDEXERS_JSON", raising=False)
    assert json.loads(_default_indexers()) == []


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
