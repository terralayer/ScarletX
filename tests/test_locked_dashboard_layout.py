from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_approved_dashboard_is_native_not_a_legacy_mutation_overlay():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    footer_css = (FRONTEND / "locked_dashboard_footer.css").read_text(encoding="utf-8")

    assert 'data-layout="approved-dashboard-v2"' in index
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
    assert '<script src="/locked_dashboard_layout.js"></script>' not in index
    assert '<link rel="stylesheet" href="/locked_dashboard.css">' in index
    assert '<link rel="stylesheet" href="/locked_dashboard_footer.css">' in index
    assert 'class="app-footer"' in index
    assert 'Discover More. Manage Smarter.' in index

    # The approved dashboard must be emitted directly by the production render
    # path. It must not depend on MutationObserver/DOM reshuffling of the legacy
    # dashboard after that dashboard has already rendered.
    dashboard_start = app.index("async function dashboard()")
    dashboard_end = app.index("function performerLinks", dashboard_start)
    dashboard = app[dashboard_start:dashboard_end]

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


def test_frontend_image_build_does_not_ship_dashboard_mutation_script():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for asset in (
        "scarletx-wordmark.svg",
        "scarletx-icon.svg",
        "scarletx-hero.svg",
        "locked_dashboard.css",
        "locked_dashboard_footer.css",
    ):
        assert f"COPY frontend/{asset} /usr/share/nginx/html/{asset}" in dockerfile

    assert "COPY frontend/locked_dashboard_layout.js" not in dockerfile
    assert "grep -q '/locked_dashboard_layout.js'" not in dockerfile
