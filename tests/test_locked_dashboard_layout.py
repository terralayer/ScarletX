from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_approved_dashboard_shell_and_brand_assets_are_wired():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    behavior = (FRONTEND / "locked_dashboard_layout.js").read_text(encoding="utf-8")

    assert 'data-layout="approved-dashboard-v1"' in index
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
    assert '<script src="/locked_dashboard_layout.js"></script>' in index
    assert '<link rel="stylesheet" href="/locked_dashboard.css">' in index

    assert '.dashboard-hero' in css
    assert '.approved-stat-grid' in css
    assert '.approved-dashboard-grid' in css
    assert '--approved-accent:#ff234f' in css.replace(' ', '')

    assert 'function applyApprovedDashboardLayout' in behavior
    assert 'Your Adult Media Library, Automated.' in behavior
    assert 'Discover. Monitor. Organize. Enjoy.' in behavior


def test_frontend_image_build_copies_locked_layout_assets():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for asset in (
        "scarletx-wordmark.svg",
        "scarletx-icon.svg",
        "scarletx-hero.svg",
        "locked_dashboard.css",
        "locked_dashboard_layout.js",
    ):
        assert f"COPY frontend/{asset} /usr/share/nginx/html/{asset}" in dockerfile
