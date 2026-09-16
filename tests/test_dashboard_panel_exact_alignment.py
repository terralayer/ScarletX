from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_dashboard_panels_use_exact_shared_geometry_and_cache_busted_css():
    cleanup = "".join((FRONTEND / "dashboard_cleanup.css").read_text(encoding="utf-8").split())
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")

    scope = 'body[data-layout="approved-dashboard-v1"]'
    assert f'{scope}.approved-dashboard-grid>.panel{{margin:0!important;align-self:stretch!important;height:auto!important;width:100%!important;box-sizing:border-box!important;display:grid!important;grid-template-rows:58pxminmax(0,1fr)!important;' in cleanup
    assert f'{scope}.approved-dashboard-grid.panel-head{{height:58px!important;min-height:58px!important;' in cleanup
    assert '<link rel="stylesheet" href="/dashboard_cleanup.css?v=approved-20260916-3">' in index
