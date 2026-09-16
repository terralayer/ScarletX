from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_top_right_user_status_is_hidden_and_downloads_uses_svg_icon():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assets = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact_assets = "".join(assets.split())

    assert '.status-pill{display:none!important;}' in compact_assets
    assert 'data-icon="top-downloads"' in index
    assert '<span class="queue-glyph">♧</span>' not in index


def test_recent_scenes_and_upcoming_releases_share_top_alignment():
    assets = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact_assets = "".join(assets.split())

    assert '.approved-dashboard-grid{align-items:start!important;}' in compact_assets
    assert '.approved-dashboard-grid.panel{align-self:start!important;' in compact_assets
    assert '.approved-dashboard-grid.panel-head{min-height:58px!important;' in compact_assets
    assert '.approved-dashboard-grid.recent{margin-top:0!important;}' in compact_assets


def test_header_search_icon_is_vertically_centered_in_search_field():
    assets = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact_assets = "".join(assets.split())

    assert '.global-search.searchmark{' in compact_assets
    assert 'top:50%!important;' in compact_assets
    assert 'transform:translateY(-50%);' in compact_assets
    assert 'pointer-events:none;' in compact_assets


def test_top_download_bell_is_centered_in_rounded_rectangle():
    assets = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact_assets = "".join(assets.split())

    assert 'body[data-layout="approved-dashboard-v1"].queue-pill{' in compact_assets
    assert 'width:44px!important;' in compact_assets
    assert 'height:40px!important;' in compact_assets
    assert 'border-radius:9px!important;' in compact_assets
    assert 'display:inline-flex!important;' in compact_assets
    assert 'align-items:center!important;' in compact_assets
    assert 'justify-content:center!important;' in compact_assets
    assert '.queue-glyph{width:22px;height:22px;display:grid;place-items:center;line-height:1;}' in compact_assets
    assert '.queue-glyphsvg{display:block;width:22px;height:22px;}' in compact_assets
    assert 'body[data-layout="approved-dashboard-v1"].queue-pill:hover,body[data-layout="approved-dashboard-v1"].queue-pill:focus-visible{border-radius:9px!important;}' in compact_assets


def test_header_uses_locked_approved_logo_asset():
    logo = (FRONTEND / "scarletx-logo.webp").read_bytes()
    assert sha256(logo).hexdigest() == "b21c56c92c573799f40572004405dcb3425c7b297e2a42e0ac9a2c15702f8250"
