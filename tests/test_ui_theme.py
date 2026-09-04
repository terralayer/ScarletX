from pathlib import Path


FRONTEND = Path(__file__).parents[1] / "frontend"
INDEX = FRONTEND / "index.html"
STYLES = FRONTEND / "styles.css"


def html() -> str:
    # Theme assertions remain byte-for-byte checks of the same CSS tokens/rules,
    # but PR9 moves the stylesheet into its own static asset.
    return INDEX.read_text(encoding="utf-8") + "\n" + STYLES.read_text(encoding="utf-8")


def test_scarlet_dark_design_tokens_are_the_default_theme():
    page = html()
    assert 'data-theme="scarlet-dark"' in page
    assert "color-scheme:dark" in page
    assert "--scarlet:#ef233c" in page
    assert "--bg:#090c11" in page
    assert "--panel:#11151c" in page
    assert "--line:#252b34" in page


def test_sidebar_uses_the_simple_scarlet_x_brandmark():
    page = html()
    assert 'class="brandmark"' in page
    assert '<span class="xslash xslash-a"></span>' in page
    assert '<span class="xslash xslash-b"></span>' in page
    assert '<div class="brandword">Scarlet<b>X</b></div>' in page


def test_dark_theme_covers_primary_ui_surfaces():
    page = html()
    required_rules = [
        ".shell{width:100%",
        ".sidebar{background:var(--sidebar)",
        ".main{background:var(--bg)",
        ".panel,.stat,.media-card,.settings-panel,.tablewrap{background:var(--panel)",
        ".input,select,textarea,.global-search input{background:var(--input)",
        ".modal{background:var(--panel)",
    ]
    for rule in required_rules:
        assert rule in page
