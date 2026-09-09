from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def section(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def test_entity_library_and_search_ignore_stale_navigation_results():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    library = section(source, "async function loadEntityLibrary", "async function searchEntity")
    search = section(source, "async function searchEntity", "function entityCard")

    assert "if(view!==type)return" in library
    assert "if(view!==type)return" in search


def test_top_level_async_pages_ignore_results_after_navigation():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    wanted = section(source, "async function wanted", "function activityQueueHtml")
    activity = section(source, "async function activity", "async function calendar")
    calendar = section(source, "async function calendar", "let settingsTab")
    settings = section(source, "async function settings", "function val")

    assert "if(view!=='wanted')return" in wanted
    assert "if(view!=='activity')return" in activity
    assert "if(view!=='calendar')return" in calendar
    assert "if(view!=='settings')return" in settings


def test_runtime_library_ignores_results_after_navigation():
    source = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")
    library = source[source.index("async function mediaLibrary"):]

    assert "if(view!=='library')return" in library
