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
    card = app[app.index("function entityCard"):app.index("function bindEntityActions")]
    assert 'data-add-only>Add</button>' in card
    assert 'data-add-monitor>Add & Monitor</button>' in card
    assert "data-add>Add & Monitor All" not in card
    assert "data-remove" not in card


def test_studio_add_and_monitor_stays_pinned_to_search_results():
    app = (ROOT / "frontend" / "app.js").read_text()
    actions = app[app.index("function bindEntityActions"):app.index("async function performerProfile")]
    assert "data-add-only" in actions
    assert "data-add-monitor" in actions
    assert "entityMode[type]='search'" in actions
    assert "entityMode[type]='library'" not in actions
    assert "renderEntities(type)" not in actions


def test_dashboard_tiles_are_real_clickable_controls_with_direct_binding():
    app = (ROOT / "frontend" / "app.js").read_text()
    assert '<button type="button" class="stat dashboard-stat"' in app
    assert "function bindDashboardStats" in app
    assert "querySelectorAll('[data-stat-go]')" in app
    assert "button.onclick" in app
    for target in ("scenes", "performers", "studios", "wanted", "library"):
        assert f"'{target}'" in app


def test_release_date_is_structurally_under_studio_in_scenes_and_media_library():
    app = (ROOT / "frontend" / "app.js").read_text()
    overrides = (ROOT / "frontend" / "ui_overrides.js").read_text()
    media = (ROOT / "scarletx" / "media_library.py").read_text()
    css = (ROOT / "frontend" / "ui_overrides.css").read_text()
    assert "studio-release" in app
    assert 'class="library-studio-meta"' in overrides
    assert 'class="library-release"' in overrides
    assert "Release: ${fmtDate(x.release_date)}" in overrides
    assert ".library-studio-meta" in css
    assert ".library-release" in css
    assert "<th>Media</th>" not in overrides
    assert '"release_date": scene.release_date' in media


def test_hydration_persists_scene_summaries_before_full_detail_crawl():
    source = (ROOT / "scarletx" / "entity_hydration.py").read_text()
    assert "cache_entity_scene_summaries" in source
    assert "details_cached" in source
    assert source.index("cache_entity_scene_summaries") < source.index("_full_scene_details")
    assert "DETAIL_BATCH_SIZE = 25" in source
    # Add -> Add & Monitor upgrades must be noticed while a large TPDB crawl is running.
    assert source.count("_job_search_requested(") >= 4
    assert "Summary-only rows may have been cached before the upgrade" in source
