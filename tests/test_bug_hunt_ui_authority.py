from pathlib import Path


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "frontend"


def test_recent_release_dashboard_lives_in_core_and_all_stats_navigate():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    stale = (FRONTEND / "dashboard_settings_overrides.js").read_text(encoding="utf-8")
    dashboard = app[app.index("async function dashboard()"):app.index("function performerLinks")]
    dashboard_core = app[app.index("function bindDashboardStats"):app.index("function performerLinks")]

    assert "dashboard=async function" not in stale
    assert "Welcome to <span>ScarletX</span>" in dashboard
    assert "Discover. Monitor. Organize. Enjoy." in dashboard
    assert "Recent Scenes" in dashboard
    assert "Upcoming Releases" in dashboard
    assert "Studios with Recent Releases" not in dashboard
    assert "Performers with Recent Releases" not in dashboard
    assert "Recently Released Scenes" not in dashboard
    for target in ("library", "performers", "studios", "calendar", "activity"):
        assert f"'{target}'" in dashboard
    assert "data-stat-go" in dashboard_core
    assert "bindDashboardStats()" in dashboard


def test_standardized_studio_art_lives_in_core_renderers_without_stale_function_copies():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    override = (FRONTEND / "studio_art_overrides.js").read_text(encoding="utf-8")
    studio_link = app[app.index("function studioLink"):app.index("function sceneRowsHtml")]
    entity_card = app[app.index("function entityCard"):app.index("function bindEntityActions")]

    assert "studioLink=function" not in override
    assert "entityCard=function" not in override
    assert "studioArtUrl(id)" not in studio_link
    assert "studioArtUrl(id)" in entity_card
    assert "renderImg=type==='studios'||!!img" in entity_card
