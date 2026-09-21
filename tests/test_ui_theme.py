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


def test_header_uses_approved_exact_logo_and_matching_icon():
    page = html()
    assert 'class="brandmark"' not in page
    assert '<span class="xslash xslash-a"></span>' not in page
    assert '<span class="xslash xslash-b"></span>' not in page
    assert '<div class="header-brand"><img src="/scarletx-wordmark.webp?v=approved-20260915-6" alt="ScarletX"></div>' in page
    assert '<link rel="icon" href="/scarletx-icon.webp?v=approved-20260918-1" type="image/webp" sizes="any">' in page
    assert "scarletx-wordmark.svg" not in page


def test_download_shortcut_keeps_the_header_rounded_rectangle_shape():
    styles = (FRONTEND / "locked_dashboard.css").read_text(encoding="utf-8")
    assert "body[data-layout=\"approved-dashboard-v1\"] .queue-pill{width:auto;min-width:112px;height:40px" in styles
    assert "body[data-layout=\"approved-dashboard-v1\"] .queue-pill{width:40px;height:40px;border:0;border-radius:50%" not in styles


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


def test_activity_exposes_pause_downloads_control():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    controls = (FRONTEND / "download_controls.js").read_text(encoding="utf-8")
    assert 'id="pauseDownloader"' in source
    assert "/api/downloads/native/control" in controls
    assert "'resume-all':'pause-all'" in controls


def test_library_media_list_and_player_omit_filename_and_audio_codec():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    overrides = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")
    rows = overrides[overrides.index("function mediaFileRowsHtml"):overrides.index("function mediaFilesHtml")]
    table = overrides[overrides.index("function mediaFilesHtml"):overrides.index("function mediaLibraryPagerHtml")]
    player = source[source.index("async function playMedia"):source.index("async function wanted")]

    assert "x.filename" not in rows
    assert "x.audio_codec" not in rows
    assert "<th>File</th>" not in table
    assert "x.missing" in rows
    assert "<b>Audio</b>" not in player


def test_library_runtime_uses_single_authoritative_media_renderer():
    source = (FRONTEND / "dashboard_settings_overrides.js").read_text(encoding="utf-8")
    overrides = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")
    assert "mediaFileRowsHtml=function(files)" not in source
    assert "function mediaFileRowsHtml(files)" in overrides
    assert 'class="library-release"' in overrides


def test_scene_rows_skip_previews_but_keep_studio_links_and_play_control():
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    rows = source[source.index("function sceneRowsHtml"):source.index("function sceneTable")]
    actions = source[source.index("function bindSceneTableActions"):source.index("async function renderEntities")]

    assert "/api/artwork/scenes/" not in rows
    assert "studioLink(x," in rows
    assert "scene-thumb" not in rows
    assert 'data-play-scene' in rows
    assert "playMedia(Number(" in actions
