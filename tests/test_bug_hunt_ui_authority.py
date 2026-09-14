from pathlib import Path


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "frontend"


def test_recent_release_dashboard_lives_in_core_and_all_stats_navigate():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    stale = (FRONTEND / "dashboard_settings_overrides.js").read_text(encoding="utf-8")
    dashboard = app[app.index("async function dashboard()"):app.index("function performerLinks")]

    assert "dashboard=async function" not in stale
    assert "Studios with Recent Releases" in dashboard
    assert "Performers with Recent Releases" in dashboard
    assert "Recently Released Scenes" in dashboard
    for target in ("library", "performers", "studios", "wanted"):
        assert f"'{target}'" in dashboard
    assert "data-stat-go" in dashboard
    assert "bindDashboardStats()" in dashboard


def test_standardized_studio_art_lives_in_core_renderers_without_stale_function_copies():
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    override = (FRONTEND / "studio_art_overrides.js").read_text(encoding="utf-8")
    studio_link = app[app.index("function studioLink"):app.index("function sceneRowsHtml")]
    entity_card = app[app.index("function entityCard"):app.index("function bindEntityActions")]

    assert "studioLink=function" not in override
    assert "entityCard=function" not in override
    assert "?v=v5" in studio_link
    assert "?v=v5" in entity_card
    assert "renderImg=type==='studios'||!!img" in entity_card
