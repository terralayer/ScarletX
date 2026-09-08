from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from scarletx.studio_art import TARGET_SIZE, prepare_studio_artwork

ROOT = Path(__file__).resolve().parents[1]


def test_studio_artwork_is_contained_with_consistent_padding():
    source = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle((10, 10, 389, 189), fill=(220, 20, 60, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    assert rendered.size == TARGET_SIZE

    alpha = rendered.getchannel("A")
    bbox = alpha.getbbox()
    assert bbox is not None
    left, top, right, bottom = bbox
    assert left >= 20
    assert top >= 20
    assert TARGET_SIZE[0] - right >= 20
    assert TARGET_SIZE[1] - bottom >= 20


def test_studio_cards_always_request_tpdb_artwork_and_use_uniform_canvas():
    override_path = ROOT / "frontend" / "studio_art_overrides.js"
    assert override_path.exists()
    source = override_path.read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")

    assert "let renderImg=type==='studios'||!!img" in source
    assert "/api/artwork/studios/" in source
    assert "renderImg?`<img" in source
    assert ".studio-card .media-poster{aspect-ratio:16/7" in css
    assert ".studio-card .media-poster img{object-fit:contain" in css


def test_studio_art_override_is_loaded_and_packaged():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert '<script src="/studio_art_overrides.js"></script>' in index
    assert "COPY frontend/studio_art_overrides.js /usr/share/nginx/html/studio_art_overrides.js" in dockerfile


def test_studio_art_route_prefers_tpdb_metadata_before_local_fallback():
    routes = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    start = routes.index('@app.get("/api/artwork/studios/{identifier}")')
    end = routes.index("\n\n@app.", start + 10)
    block = routes[start:end]

    assert "tpdb_identifier = local.tpdb_id if local and local.tpdb_id else identifier" in block
    assert "studio = await tpdb.get_studio(tpdb_identifier)" in block
    assert "urls = [value for value in (studio.logo_url, studio.poster_url) if value]" in block
    assert block.index("studio = await tpdb.get_studio(tpdb_identifier)") < block.index("local_urls =")


def test_studio_art_cache_is_versioned_for_new_normalization():
    source = (ROOT / "scarletx" / "studio_art.py").read_text(encoding="utf-8")
    assert 'STUDIO_ART_CACHE_VERSION = "v2"' in source
    assert 'f"{STUDIO_ART_CACHE_VERSION}-{identifier}.png"' in source


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
