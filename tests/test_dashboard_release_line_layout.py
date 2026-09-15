from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def dashboard_source() -> str:
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    start = app.index("function dashboardRecentRows")
    return app[start:app.index("function performerLinks", start)]


def test_dashboard_recent_scene_uses_separate_title_meta_and_date_elements():
    dashboard = dashboard_source()

    assert 'class="approved-recent-title"' in dashboard
    assert 'class="approved-recent-meta"' in dashboard
    assert 'class="approved-recent-date"' in dashboard
    assert "dashboardStudioName(scene)" in dashboard
    assert "fmtDate(scene.release_date)" in dashboard


def test_dashboard_recent_scene_layout_is_defined_by_approved_dashboard_css():
    css = (ROOT / "frontend" / "locked_dashboard.css").read_text(encoding="utf-8")
    compact = "".join(css.split())

    assert ".approved-recent-row" in compact
    assert ".approved-recent-title" in compact
    assert ".approved-recent-meta" in compact
    assert ".approved-recent-date" in compact


def test_removed_legacy_release_panels_do_not_reappear():
    dashboard = dashboard_source()

    assert "studioReleaseRows" not in dashboard
    assert "performerReleaseRows" not in dashboard
    assert "Studios with Recent Releases" not in dashboard
    assert "Performers with Recent Releases" not in dashboard


def test_dashboard_recent_scene_rows_open_scene_detail_directly():
    dashboard = dashboard_source()

    assert 'data-dashboard-scene="${esc(localId)}"' in dashboard
    assert "openLocalScene(localId)" in dashboard
