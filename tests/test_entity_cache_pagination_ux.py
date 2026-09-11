from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_activity_pagination_has_single_state_owner():
    app = (ROOT / "frontend" / "app.js").read_text()
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text()
    assert "const ACTIVITY_QUEUE_PAGE_SIZE=50" in app
    assert "let activityQueuePage=1" in app
    assert "const ACTIVITY_QUEUE_PAGE_SIZE=50" not in overrides
    assert "let activityQueuePage=1" not in overrides


def test_entity_add_actions_are_add_or_add_and_monitor_without_delete():
    app = (ROOT / "frontend" / "app.js").read_text()
    assert 'data-add-only>Add</button>' in app
    assert 'data-add-monitor>Add & Monitor</button>' in app
    assert "data-add>Add & Monitor All" not in app
    assert "if(type==='performers'||type==='studios')" in app
    assert "data-remove" not in app[app.index("function entityCard"):app.index("function bindEntityActions")]


def test_studio_add_stays_on_search_results():
    app = (ROOT / "frontend" / "app.js").read_text()
    actions = app[app.index("function bindEntityActions"):app.index("async function performerProfile")]
    assert "data-add-only" in actions
    assert "data-add-monitor" in actions
    assert "entityMode[type]='library'" not in actions
    assert "renderEntities(type)" not in actions


def test_dashboard_tiles_are_clickable():
    app = (ROOT / "frontend" / "app.js").read_text()
    assert "data-stat-go" in app
    for target in ("scenes", "performers", "studios", "wanted", "library"):
        assert f"'{target}'" in app


def test_release_date_is_under_studio_and_library_media_column_is_removed():
    app = (ROOT / "frontend" / "app.js").read_text()
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text()
    media = (ROOT / "scarletx" / "media_library.py").read_text()
    assert "studio-release" in app
    assert "studio-release" in overrides
    assert "<th>Media</th>" not in overrides
    assert '"release_date": scene.release_date' in media


def test_hydration_persists_scene_summaries_before_full_detail_crawl():
    source = (ROOT / "scarletx" / "entity_hydration.py").read_text()
    assert "cache_entity_scene_summaries" in source
    assert "details_cached" in source
    assert source.index("cache_entity_scene_summaries") < source.index("_full_scene_details")
    assert "DETAIL_BATCH_SIZE = 25" in source
