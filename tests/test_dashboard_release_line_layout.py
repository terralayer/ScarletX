from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def dashboard_source() -> str:
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    return app[app.index("async function dashboard()"):app.index("function performerLinks")]


def test_dashboard_performer_release_title_and_date_are_separate_lines():
    dashboard = dashboard_source()

    assert 'class="dashboard-release-title"' in dashboard
    assert 'class="dashboard-release-date"' in dashboard
    assert "${esc(x.latest_title||'Latest downloaded release')} · ${fmtDate(x.latest_release_date)}" not in dashboard


def test_dashboard_recent_scene_title_and_date_are_separate_lines():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    dashboard = dashboard_source()
    scene_rows = app[app.index("function sceneRowsHtml"):app.index("function sceneTable")]

    assert "sceneTable(scenes,true,true)" in dashboard
    assert "releaseDateUnderScene" in scene_rows
    assert 'class="dashboard-release-date"' in scene_rows
    assert "studioLink(x,!releaseDateUnderScene)" in scene_rows
