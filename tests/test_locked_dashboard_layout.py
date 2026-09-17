import base64
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BANNER_SHA256 = "236fc1fdadd8c34fa5909dcf7d5dae6e346b410e04bf89c0409fc341fee02cad"
WORDMARK_SHA256 = "a90efeaa68b2f8a96e20d62167582f79ed58ef92aa776e46e8c4d9bad0e3c3ca"
ICON_SHA256 = "30f7d52a474ed83d7f6f83d8da8ec9ca3488b6936bced0072dccdf762c10e768"
EXPECTED_CHUNK_BLOBS = {
    1: "c0a9c496504b1761110a3b62b6e3ed46d6a0b6e5",
    2: "9b15ff7f2f5b1a4ec8558340aa04fd36277dd2df",
    3: "7afcd8c8b1943ecc3892624eb6880e068e6d4b46",
    4: "04fbf4d1a2e8ba5d0ef258a0406eeee160f98fcd",
}


def _git_blob_sha(data: bytes) -> str:
    return __import__("hashlib").sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def test_approved_dashboard_is_native_in_core_runtime():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = (FRONTEND / "app.js").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    footer_css = (FRONTEND / "locked_dashboard_footer.css").read_text(encoding="utf-8")
    approved_assets_css = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")

    assert 'data-layout="approved-dashboard-v1"' in index
    assert 'data-dashboard-render="native-v2"' in index
    assert '/scarletx-wordmark.webp?v=approved-20260915-6' in index
    assert '/scarletx-icon.svg?v=approved-20260916-1' in index
    for label in ("Dashboard", "Performers", "Scenes", "Studios", "Calendar", "Downloads", "Indexers", "Settings"):
        assert f'<span>{label}</span>' in index
    assert '<script src="/dashboard_v2.js"></script>' not in index
    assert '<script src="/locked_dashboard_layout.js"></script>' not in index
    assert '<link rel="stylesheet" href="/approved_assets.css">' in index
    assert '<link rel="stylesheet" href="/ui_icons.css">' in index
    assert '<link rel="stylesheet" href="/dashboard_cleanup.css">' in index
    assert '<link rel="stylesheet" href="/sidebar_compact.css">' in index
    assert 'Discover More. Manage Smarter.' in index

    dashboard_start = app.index("async function dashboard()")
    dashboard_end = app.index("function performerLinks", dashboard_start)
    dashboard = app[dashboard_start:dashboard_end]
    assert 'class="dashboard-hero"' in dashboard
    assert 'class="stats approved-stat-grid"' in dashboard
    assert 'class="approved-dashboard-grid"' in dashboard
    assert 'id="recentScenes"' in dashboard
    assert 'id="calendarRows"' in dashboard
    assert 'MutationObserver' not in dashboard

    assert '.dashboard-hero' in css
    assert '.app-footer' in footer_css
    assert "url('/scarletx-banner.webp')" in approved_assets_css
    assert 'aspect-ratio:1321 / 163' in approved_assets_css
    assert '.dashboard-hero::after{display:none!important}' in approved_assets_css


def test_approved_layout_hides_legacy_side_footer_entirely():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    css = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    footer_css = (FRONTEND / "locked_dashboard_footer.css").read_text(encoding="utf-8")

    assert 'class="side-footer"' not in index
    assert 'body[data-layout="approved-dashboard-v1"] .side-footer{display:none!important}' in css
    assert 'body[data-layout="approved-dashboard-v1"] .main::after{content:none!important;display:none!important}' in footer_css


def test_desktop_sidebar_is_tight_but_usable():
    compact = "".join((FRONTEND / "sidebar_compact.css").read_text(encoding="utf-8").split())
    locked = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")

    assert '@media(min-width:981px){' in compact
    assert '.shell{grid-template-columns:242pxminmax(0,1fr)}' in compact
    assert '.nav{padding:18px10px14px;display:grid;gap:5px}' in compact
    assert '.navbutton{height:44px;padding:016px;gap:12px;font-size:15px}' in compact
    assert '.nav.ico{width:19px;height:19px;font-size:17px}' in compact
    assert '@media(max-width:980px){body[data-layout="approved-dashboard-v1"] .shell{grid-template-columns:82px 1fr;' in locked


def test_dashboard_stat_cards_scale_across_desktop_widths():
    compact = "".join((FRONTEND / "dashboard_cleanup.css").read_text(encoding="utf-8").split())

    assert '@media(min-width:981px){' in compact
    assert '.stats.approved-stat-grid{grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:clamp(10px,1.2vw,18px)!important;' in compact
    assert '.approved-stat-grid.stat{min-height:clamp(128px,10vw,162px)!important;' in compact
    assert 'padding:clamp(14px,1.4vw,20px)clamp(14px,1.5vw,22px)!important;' in compact
    assert 'grid-template-columns:clamp(34px,3.5vw,46px)minmax(0,1fr)!important;' in compact
    assert 'gap:clamp(8px,1vw,16px)!important;' in compact
    assert '.approved-stat-grid.stat-icon{width:clamp(34px,3.3vw,42px)!important;height:clamp(34px,3.3vw,42px)!important;' in compact
    assert '.approved-stat-grid.stat-iconsvg{width:clamp(27px,2.7vw,34px)!important;height:clamp(27px,2.7vw,34px)!important;' in compact
    assert '.approved-stat-grid.statsmall{font-size:clamp(12px,1.05vw,15px)!important;' in compact
    assert '.approved-stat-grid.statstrong{font-size:clamp(24px,2.15vw,32px)!important;' in compact
    assert '.approved-stat-grid.statem{font-size:clamp(11px,.95vw,14px)!important;' in compact


def test_dashboard_cleanup_hides_profile_and_banner_copy_and_levels_panels():
    cleanup = FRONTEND / "dashboard_cleanup.css"
    assert cleanup.exists()
    compact = "".join(cleanup.read_text(encoding="utf-8").split())
    assert '.status-pill{display:none!important;}' in compact
    assert '.dashboard-hero-copy{display:none!important;}' in compact
    assert '.approved-dashboard-grid{align-items:stretch!important;}' in compact
    assert '.approved-dashboard-grid>.panel{margin:0!important;align-self:stretch!important;height:auto!important;width:100%!important;box-sizing:border-box!important;display:grid!important;grid-template-rows:58pxminmax(0,1fr)!important;' in compact
    assert '.approved-dashboard-grid.panel-head{height:58px!important;min-height:58px!important;' in compact
    assert 'align-items:start!important' not in compact
    assert 'align-self:start!important' not in compact


def test_dashboard_recent_and_upcoming_rows_share_vertical_rhythm():
    cleanup = "".join((FRONTEND / "dashboard_cleanup.css").read_text(encoding="utf-8").split())
    scope = 'body[data-layout="approved-dashboard-v1"]'

    assert f'{scope}.approved-recent-list,{scope}.approved-upcoming.rows{{padding:4px20px14px!important;' in cleanup
    assert f'{scope}.approved-recent-row,{scope}.approved-upcoming.row{{min-height:65px!important;height:65px!important;padding:8px0!important;box-sizing:border-box!important;' in cleanup


def test_approved_banner_source_reconstructs_to_locked_bytes():
    chunks = []
    for part, expected_blob in EXPECTED_CHUNK_BLOBS.items():
        data = (FRONTEND / f"scarletx-banner.b64.{part}").read_bytes()
        assert _git_blob_sha(data) == expected_blob
        chunks.append(data.decode("ascii"))
    banner = base64.b64decode("".join(chunks), validate=True)
    assert sha256(banner).hexdigest() == BANNER_SHA256
    assert banner.startswith(b"RIFF")
    assert b"WEBP" in banner[:16]


def test_frontend_image_build_uses_checksum_locked_brand_assets():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    for asset in ("locked_dashboard.css", "locked_dashboard_footer.css", "approved_assets.css", "ui_icons.css", "dashboard_cleanup.css", "sidebar_compact.css"):
        assert f"COPY frontend/{asset} /usr/share/nginx/html/{asset}" in dockerfile
    for part in range(4):
        assert f"COPY frontend/scarletx-wordmark.webp.b64.{part:02d} /tmp/scarletx-wordmark.webp.b64.{part:02d}" in dockerfile
    assert "COPY frontend/scarletx-icon.svg /usr/share/nginx/html/scarletx-icon.svg" in dockerfile
    assert "COPY frontend/scarletx-icon.webp /usr/share/nginx/html/scarletx-icon.webp" in dockerfile
    assert WORDMARK_SHA256 in dockerfile
    assert ICON_SHA256 in dockerfile
    for part in range(1, 5):
        assert f"COPY frontend/scarletx-banner.b64.{part} /tmp/scarletx-banner.b64.{part}" in dockerfile
    assert BANNER_SHA256 in dockerfile
    assert "COPY frontend/scarletx-wordmark.svg" not in dockerfile
    assert "COPY frontend/scarletx-hero.svg" not in dockerfile
    assert "COPY frontend/dashboard_v2.js" not in dockerfile
    assert "COPY frontend/locked_dashboard_layout.js" not in dockerfile
