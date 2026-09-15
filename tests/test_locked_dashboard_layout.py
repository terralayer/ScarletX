from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_approved_dashboard_is_native_not_a_legacy_mutation_overlay():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    dashboard = (FRONTEND / "dashboard_v2.js").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    footer_css = (FRONTEND / "locked_dashboard_footer.css").read_text(encoding="utf-8")

    assert 'data-layout="approved-dashboard-v1"' in index
    assert 'data-dashboard-render="native-v2"' in index
    assert '/scarletx-wordmark.svg' in index
    assert '/scarletx-icon.svg' in index
    assert '<span>Dashboard</span>' in index
    assert '<span>Performers</span>' in index
    assert '<span>Scenes</span>' in index
    assert '<span>Studios</span>' in index
    assert '<span>Calendar</span>' in index
    assert '<span>Discover</span>' in index
    assert '<span>Downloads</span>' in index
    assert '<span>Indexers</span>' in index
    assert '<span>Settings</span>' in index
    assert '<script src="/dashboard_v2.js"></script>' in index
    assert '<script src="/locked_dashboard_layout.js"></script>' not in index
    assert '<link rel="stylesheet" href="/locked_dashboard.css">' in index
    assert '<link rel="stylesheet" href="/locked_dashboard_footer.css">' in index
    assert 'class="app-footer"' in index
    assert 'Discover More. Manage Smarter.' in index

    # The approved dashboard is emitted directly by the production renderer.
    # No MutationObserver or legacy dashboard DOM reshuffling is allowed.
    assert 'dashboard = async function dashboard' in dashboard
    assert 'MutationObserver' not in dashboard
    assert 'class="dashboard-hero"' in dashboard
    assert 'Discover. Monitor. Organize. Enjoy.' in dashboard
    assert 'class="stats approved-stat-grid"' in dashboard
    assert 'class="approved-dashboard-grid"' in dashboard
    assert 'id="recentScenes"' in dashboard
    assert 'id="calendarRows"' in dashboard
    assert 'Recent Scenes' in dashboard
    assert 'Upcoming Releases' in dashboard
    assert 'Studios with Recent Releases' not in dashboard
    assert 'Performers with Recent Releases' not in dashboard

    assert '.dashboard-hero' in css
    assert '.approved-stat-grid' in css
    assert '.approved-dashboard-grid' in css
    assert '--approved-accent:#ff234f' in css.replace(' ', '')
    assert '.app-footer' in footer_css


def test_frontend_image_build_ships_native_dashboard_not_mutation_script():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for asset in (
        "scarletx-wordmark.svg",
        "scarletx-icon.svg",
        "scarletx-hero.svg",
        "locked_dashboard.css",
        "locked_dashboard_footer.css",
        "dashboard_v2.js",
    ):
        assert f"COPY frontend/{asset} /usr/share/nginx/html/{asset}" in dockerfile

    assert "COPY frontend/locked_dashboard_layout.js" not in dockerfile
    assert "grep -q '/locked_dashboard_layout.js'" not in dockerfile
    assert "grep -q '/dashboard_v2.js'" in dockerfile
