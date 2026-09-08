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


def test_activity_exposes_native_downloader_restart_control():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert 'id="restartDownloader"' in source
    assert "/api/download-client/restart" in source
    assert "requeued" in source


def test_library_media_list_and_player_omit_filename_and_audio_codec():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    rows = source[source.index("function mediaFileRowsHtml"):source.index("function mediaFilesHtml")]
    table = source[source.index("function mediaFilesHtml"):source.index("function mediaPageUrl")]
    player = source[source.index("async function playMedia"):source.index("async function wanted")]

    assert "x.filename" not in rows
    assert "x.audio_codec" not in rows
    assert "<th>File</th>" not in table
    assert "x.missing" in rows
    assert "<b>Audio</b>" not in player


def test_scene_rows_show_tpdb_artwork_studio_logo_and_play_control():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    rows = source[source.index("function sceneRowsHtml"):source.index("function sceneTable")]
    actions = source[source.index("function bindSceneTableActions"):source.index("async function renderEntities")]

    assert "/api/artwork/scenes/" in rows
    assert "/api/artwork/studios/" in source
    assert "?size=card" in rows
    assert 'data-play-scene' in rows
    assert "playMedia(Number(" in actions
    assert ".scene-thumb" in styles
    assert ".studio-logo" in styles
