from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_dashboard_panels_use_exact_shared_geometry():
    cleanup = "".join((FRONTEND / "dashboard_cleanup.css").read_text(encoding="utf-8").split())

    scope = 'body[data-layout="approved-dashboard-v1"]'
    assert f'{scope}.approved-dashboard-grid>.panel{{margin:0!important;align-self:stretch!important;height:auto!important;width:100%!important;box-sizing:border-box!important;display:grid!important;grid-template-rows:58pxminmax(0,1fr)!important;' in cleanup
    assert f'{scope}.approved-dashboard-grid.panel-head{{height:58px!important;min-height:58px!important;' in cleanup


def test_frontend_css_and_js_are_revalidated_after_image_upgrade():
    nginx = (ROOT / "nginx" / "scarletx.conf").read_text(encoding="utf-8")

    assert "location ~* \\.(css|js)$" in nginx
    assert "expires -1;" in nginx
