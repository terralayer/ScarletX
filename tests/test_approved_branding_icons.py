from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
WORDMARK_SHA256 = "a90efeaa68b2f8a96e20d62167582f79ed58ef92aa776e46e8c4d9bad0e3c3ca"
ICON_SHA256 = "30f7d52a474ed83d7f6f83d8da8ec9ca3488b6936bced0072dccdf762c10e768"


def test_shell_keeps_approved_wordmark_source_and_emblem_favicon_available():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert '<div class="header-brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6" alt="ScarletX"></div>' in index
    assert '<div class="brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6" alt="ScarletX"></div>' in index
    assert '<link rel="icon" href="/scarletx-icon.webp?v=approved-20260915-6" type="image/webp">' in index
    assert "scarletx-wordmark.svg" not in index
    assert "scarletx-icon.svg" not in index


def test_sidebar_and_topbar_use_svg_icons_not_unicode_glyphs():
    index = (FRONTEND / "index.html").read_text(encoding="utf-8")
    for icon_id in (
        "nav-home", "nav-performers", "nav-scenes", "nav-studios", "nav-calendar",
        "nav-discover", "nav-downloads", "nav-indexers", "nav-settings",
        "top-search", "top-bell", "top-user",
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
    for part in range(4):
        assert f"COPY frontend/scarletx-wordmark.webp.b64.{part:02d} /tmp/scarletx-wordmark.webp.b64.{part:02d}" in dockerfile
    assert "COPY frontend/scarletx-icon.webp /usr/share/nginx/html/scarletx-icon.webp" in dockerfile
    assert WORDMARK_SHA256 in dockerfile
    assert ICON_SHA256 in dockerfile
    assert "COPY frontend/scarletx-wordmark.svg" not in dockerfile
    assert "COPY frontend/scarletx-icon.svg" not in dockerfile
    assert 'head -c 4 /usr/share/nginx/html/scarletx-wordmark.webp' in dockerfile
    assert 'head -c 4 /usr/share/nginx/html/scarletx-icon.webp' in dockerfile


def test_branding_shows_approved_logo_without_a_broken_image_box():
    css = (FRONTEND / "approved_assets.css").read_text(encoding="utf-8")
    compact = "".join(css.split())
    assert ".brandimg,.header-brandimg{display:none!important;width:0!important;height:0!important;" in compact
    assert "background-image:url('/scarletx-wordmark.webp?v=approved-20260915-7')!important" in compact
    assert "background-size:contain!important" in compact
    assert ".brand{width:180px!important;height:60px!important" in compact
    assert ".header-brand{width:150px!important;height:48px!important" in compact
    assert "box-shadow:none!important" in compact
