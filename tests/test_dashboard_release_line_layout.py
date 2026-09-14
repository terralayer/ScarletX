from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Dashboard-only layout contract for studio/performer recent releases and recent scenes;
# normal Scenes/Library tables stay unchanged.


def dashboard_source() -> str:
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    return app[app.index("async function dashboard()"):app.index("function performerLinks")]


def test_dashboard_release_date_is_smaller_than_release_title():
    styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    compact = "".join(styles.split())
    assert ".dashboard-release-title{display:block;font-size:9px;color:var(--muted);line-height:1.35;margin-top:2px}" in compact
    assert ".dashboard-release-date{display:block;font-size:8px;color:var(--muted);line-height:1.2;margin-top:1px}" in compact
    assert ".dashboard-scene-copy.scene-title{display:block}" in compact


def test_dashboard_studio_release_title_and_date_are_separate_lines():
    dashboard = dashboard_source()
    start = dashboard.index("$('#studioReleaseRows')")
    end = dashboard.index("$('#performerReleaseRows')", start)
    studio_rows = dashboard[start:end]

    assert 'class="dashboard-release-title"' in studio_rows
    assert 'class="dashboard-release-date"' in studio_rows
    assert "${esc(x.latest_title||'Latest downloaded release')} · ${fmtDate(x.latest_release_date)}" not in studio_rows


def test_dashboard_performer_release_title_and_date_are_separate_lines():
    dashboard = dashboard_source()
    start = dashboard.index("$('#performerReleaseRows')")
    end = dashboard.index("$('#calendarRows')", start)
    performer_rows = dashboard[start:end]

    assert 'class="dashboard-release-title"' in performer_rows
    assert 'class="dashboard-release-date"' in performer_rows
    assert "${esc(x.latest_title||'Latest downloaded release')} · ${fmtDate(x.latest_release_date)}" not in performer_rows


def test_dashboard_recent_scene_title_and_date_are_separate_lines():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    dashboard = dashboard_source()
    scene_rows = app[app.index("function sceneRowsHtml"):app.index("function sceneTable")]

    assert "sceneTable(scenes,true,true)" in dashboard
    assert "releaseDateUnderScene" in scene_rows
    assert 'class="dashboard-release-date"' in scene_rows
    assert "studioLink(x,!releaseDateUnderScene)" in scene_rows
