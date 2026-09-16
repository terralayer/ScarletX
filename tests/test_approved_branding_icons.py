from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_shell_uses_approved_wordmark_and_emblem_favicon_directly():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<div class="header-brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-5" alt="ScarletX"></div>' in index
    assert '<div class="brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-5" alt="ScarletX"></div>' in index
    assert '<link rel="icon" href="/scarletx-icon.webp?v=approved-20260915-5" type="image/webp">' in index
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


def test_web_image_extracts_and_validates_approved_brand_assets_without_runtime_url_rewrite():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "COPY frontend/scarletx-wordmark.svg /tmp/scarletx-wordmark.svg" in dockerfile
    assert "COPY frontend/scarletx-icon.svg /tmp/scarletx-icon.svg" in dockerfile
    assert "> /usr/share/nginx/html/scarletx-wordmark.webp" in dockerfile
    assert "> /usr/share/nginx/html/scarletx-icon.webp" in dockerfile
    assert 'head -c 4 /usr/share/nginx/html/scarletx-wordmark.webp' in dockerfile
    assert 'skip=8 count=4' in dockerfile
    assert "s#/scarletx-wordmark.svg" not in dockerfile
    assert "s#/scarletx-icon.svg" not in dockerfile
    assert "COPY frontend/ui_icons.css /usr/share/nginx/html/ui_icons.css" in dockerfile


def test_approved_brand_assets_have_explicit_visible_dimensions():
    css = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact = "".join(css.split())
    assert ".brandimg{display:block;width:180px;max-width:100%;height:auto;object-fit:contain;}" in compact
    assert ".header-brandimg{display:block;width:150px;max-width:100%;max-height:48px;height:auto;object-fit:contain;}" in compact
