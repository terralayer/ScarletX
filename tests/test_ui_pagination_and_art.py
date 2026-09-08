from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_ui_overrides_are_loaded_after_main_frontend_assets():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert 'href="/styles.css"' in html
    assert 'href="/ui_overrides.css"' in html
    assert html.index('href="/styles.css"') < html.index('href="/ui_overrides.css"')
    assert 'src="/app.js"' in html
    assert 'src="/ui_overrides.js"' in html
    assert html.index('src="/app.js"') < html.index('src="/ui_overrides.js"')


def test_web_image_copies_ui_override_assets():
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert "COPY frontend/ui_overrides.css /usr/share/nginx/html/ui_overrides.css" in dockerfile
    assert "COPY frontend/ui_overrides.js /usr/share/nginx/html/ui_overrides.js" in dockerfile


def test_queue_override_paginates_50_rows_and_moves_eta_to_own_line():
    source = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")
    assert "const ACTIVITY_QUEUE_PAGE_SIZE=50" in source
    assert "rows.slice(start,start+ACTIVITY_QUEUE_PAGE_SIZE)" in source
    assert 'class="live-eta-row"' in source
    assert "Speed / ETA" not in source
    assert 'data-queue-page="first"' in source
    assert 'data-queue-page="prev"' in source
    assert 'data-queue-page="next"' in source


def test_library_override_paginates_50_rows_with_tpdb_art_and_studio_line():
    source = (FRONTEND / "ui_overrides.js").read_text(encoding="utf-8")
    assert "const MEDIA_LIBRARY_PAGE_SIZE=50" in source
    assert "/api/media-library/files/page?limit=${MEDIA_LIBRARY_PAGE_SIZE}" in source
    assert "cursor=${encodeURIComponent(cursor)}" in source
    assert "/api/artwork/scenes/${encodeURIComponent(x.scene_id)}?size=card" in source
    assert 'class="library-studio"' in source
    assert 'data-library-page="first"' in source
    assert 'data-library-page="prev"' in source
    assert 'data-library-page="next"' in source
    assert "audio_codec" not in source
    assert ">Audio<" not in source


def test_library_artwork_route_accepts_local_scene_ids():
    routes = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    artwork = routes[routes.index('@app.get("/api/artwork/scenes/{identifier}")'):]
    artwork = artwork[:artwork.index('@app.get("/api/artwork/studios/{identifier}")')]
    assert "identifier.isdigit()" in artwork
    assert "db.get(Scene, int(identifier))" in artwork
