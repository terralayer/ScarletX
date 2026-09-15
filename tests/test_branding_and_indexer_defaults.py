from pathlib import Path

from scarletx.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_install_has_no_preloaded_indexers(monkeypatch):
    monkeypatch.delenv("SCARLETX_NEWZNAB_INDEXERS_JSON", raising=False)
    settings = Settings()
    assert settings.newznab_indexers() == []
    assert settings.newznab_indexers_json.get_secret_value() == "[]"


def test_approved_full_logo_is_used_in_shell():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert '<div class="header-brand"><img src="/scarletx-wordmark.svg"' in index
    assert '<div class="brand"><img src="/scarletx-wordmark.svg"' in index


def test_bundled_indexer_seed_code_is_removed():
    source = (ROOT / "scarletx" / "settings_store.py").read_text(encoding="utf-8")
    for marker in (
        "dev_nzbgeek_083_applied",
        "dev_treasure_maps_084_applied",
        "dev_nzblife_085_applied",
        "dev_usenet_crawler_085_applied",
    ):
        assert marker not in source
