from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

WORDMARK_SHA256 = "516ba81139519bf0021d06355010b20b1316f3cf9273e42778d7ca02e83ec569"
ICON_SHA256 = "b53beae4da1a67eabaeec72f0c53c0bf77ca2f627e92f6ad5f35b673908b6c50"


def test_shell_uses_approved_wordmark_and_emblem_favicon_directly():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<div class="header-brand"><img src="/scarletx-wordmark.png?v=approved-20260915-4" alt="ScarletX"></div>' in index
    assert '<div class="brand"><img src="/scarletx-wordmark.png?v=approved-20260915-4" alt="ScarletX"></div>' in index
    assert '<link rel="icon" href="/scarletx-icon.png?v=approved-20260915-4" type="image/png">' in index
    assert "scarletx-wordmark.svg" not in index
    assert "scarletx-icon.svg" not in index


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


def test_web_image_reconstructs_and_verifies_approved_brand_assets():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "COPY frontend/scarletx-wordmark.png.b64 /tmp/scarletx-wordmark.png.b64" in dockerfile
    assert "COPY frontend/scarletx-icon.png.b64 /tmp/scarletx-icon.png.b64" in dockerfile
    assert "base64 -d /tmp/scarletx-wordmark.png.b64 > /usr/share/nginx/html/scarletx-wordmark.png" in dockerfile
    assert "base64 -d /tmp/scarletx-icon.png.b64 > /usr/share/nginx/html/scarletx-icon.png" in dockerfile
    assert WORDMARK_SHA256 in dockerfile
    assert ICON_SHA256 in dockerfile
    assert "href=\"data:image/webp;base64" not in dockerfile
    assert "COPY frontend/ui_icons.css /usr/share/nginx/html/ui_icons.css" in dockerfile
