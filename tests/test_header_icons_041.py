import base64
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
    encoded = "".join(
        (FRONTEND / f"scarletx-logo.b64.{part}").read_text(encoding="utf-8").strip()
        for part in range(1, 5)
    )
    logo = base64.b64decode(encoded, validate=True)
    assert sha256(logo).hexdigest() == "a81e85a5899b7432b6a3fd557d5eb9f9a5b7ec451476dfa6897425d7830f8a4c"

    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "COPY frontend/scarletx-logo.b64.1 /tmp/scarletx-logo.b64.1" in dockerfile
    assert "a81e85a5899b7432b6a3fd557d5eb9f9a5b7ec451476dfa6897425d7830f8a4c  /usr/share/nginx/html/scarletx-logo.webp" in dockerfile
    assert "COPY frontend/scarletx-logo.webp /usr/share/nginx/html/scarletx-logo.webp" not in dockerfile
