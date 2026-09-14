from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Dashboard-only layout contract for performers and recent scenes; normal Scenes/Library tables stay unchanged.


def dashboard_source() -> str:
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    return app[app.index("async function dashboard()"):app.index("function performerLinks")]


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
