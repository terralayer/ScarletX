from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_shell_uses_approved_wordmark_and_emblem_favicon():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<div class="header-brand"><img src="/scarletx-wordmark.svg?v=approved-20260915-2" alt="ScarletX"></div>' in index
    assert '<div class="brand"><img src="/scarletx-wordmark.svg?v=approved-20260915-2" alt="ScarletX"></div>' in index
    assert '<link rel="icon" href="/scarletx-icon.svg?v=approved-20260915-2" type="image/svg+xml">' in index
    assert "scarletx-logo.webp" not in index
    assert "scarletx-icon.webp" not in index


def test_sidebar_and_topbar_use_svg_icons_not_unicode_glyphs():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for icon_id in (
        "nav-home",
        "nav-performers",
        "nav-scenes",
        "nav-studios",
        "nav-calendar",
        "nav-discover",
        "nav-downloads",
        "nav-indexers",
        "nav-settings",
        "top-search",
        "top-bell",
        "top-user",
    ):
        assert f'data-icon="{icon_id}"' in index

    for glyph in ("⌂", "♙", "▣", "▥", "▦", "⌕", "⇩", "⬡", "⚙", "♧"):
        assert glyph not in index


def test_vector_icons_have_consistent_css_contract():
    css = (FRONTEND / "ui_icons.css").read_text(encoding="utf-8")
    compact = "".join(css.split())
    assert '.nav.icosvg{width:22px;height:22px;display:block;stroke:currentColor;fill:none' in compact
    assert '.searchmarksvg' in compact
    assert '.queue-glyphsvg' in compact
    assert '.profile-glyphsvg' in compact


def test_web_image_bundles_approved_brand_assets():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "COPY frontend/scarletx-wordmark.svg /usr/share/nginx/html/scarletx-wordmark.svg" in dockerfile
    assert "COPY frontend/scarletx-icon.svg /usr/share/nginx/html/scarletx-icon.svg" in dockerfile
    assert "COPY frontend/ui_icons.css /usr/share/nginx/html/ui_icons.css" in dockerfile
