from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_approved_dashboard_is_native_in_core_runtime():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    footer_css = (FRONTEND / "locked_dashboard_footer.css").read_text(encoding="utf-8")
    approved_assets_css = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")

    assert 'data-layout="approved-dashboard-v1"' in index
    assert 'data-dashboard-render="native-v2"' in index
    assert '/scarletx-logo.webp' in index
    assert '/scarletx-icon.webp' in index
    assert '<span>Dashboard</span>' in index
    assert '<span>Performers</span>' in index
    assert '<span>Scenes</span>' in index
    assert '<span>Studios</span>' in index
    assert '<span>Calendar</span>' in index
    assert '<span>Discover</span>' in index
    assert '<span>Downloads</span>' in index
    assert '<span>Indexers</span>' in index
    assert '<span>Settings</span>' in index
    assert '<script src="/dashboard_v2.js"></script>' not in index
    assert '<script src="/locked_dashboard_layout.js"></script>' not in index
    assert '<link rel="stylesheet" href="/locked_dashboard.css">' in index
    assert '<link rel="stylesheet" href="/locked_dashboard_footer.css">' in index
    assert '<link rel="stylesheet" href="/approved_assets.css">' in index
    assert 'class="app-footer"' in index
    assert 'Discover More. Manage Smarter.' in index

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
    assert 'MutationObserver' not in dashboard

    assert '.dashboard-hero' in css
    assert '.approved-stat-grid' in css
    assert '.approved-dashboard-grid' in css
    assert '--approved-accent:#ff234f' in css.replace(' ', '')
    assert '.app-footer' in footer_css
    assert "url('/scarletx-banner.webp')" in approved_assets_css
    assert 'aspect-ratio:1321 / 163' in approved_assets_css
    assert '.dashboard-hero::after{display:none!important}' in approved_assets_css


def test_approved_banner_is_the_exact_locked_mock_crop():
    banner = (FRONTEND / "scarletx-banner.webp").read_bytes()
    assert sha256(banner).hexdigest() == "95cc5f51a068a850a9b3654de867de01e90468feea9ce2077c5e351cb9055dab"


def test_frontend_image_build_has_no_dashboard_override_or_mutation_script():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for asset in (
        "scarletx-logo.webp",
        "scarletx-icon.webp",
        "scarletx-banner.webp",
        "locked_dashboard.css",
        "locked_dashboard_footer.css",
        "approved_assets.css",
    ):
        assert f"COPY frontend/{asset} /usr/share/nginx/html/{asset}" in dockerfile

    assert "COPY frontend/scarletx-hero.svg" not in dockerfile
    assert "COPY frontend/dashboard_v2.js" not in dockerfile
    assert "COPY frontend/locked_dashboard_layout.js" not in dockerfile
    assert "grep -q '/dashboard_v2.js'" not in dockerfile
    assert "grep -q '/locked_dashboard_layout.js'" not in dockerfile
