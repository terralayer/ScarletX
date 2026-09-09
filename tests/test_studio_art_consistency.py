from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from scarletx.studio_art import TARGET_SIZE, prepare_studio_artwork, trim_logo_whitespace

ROOT = Path(__file__).resolve().parents[1]


def test_studio_artwork_is_contained_with_consistent_padding():
    source = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.rectangle((10, 10, 389, 189), fill=(220, 20, 60, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    assert rendered.size == TARGET_SIZE

    background = rendered.getpixel((0, 0))[:3]
    bbox = _mark_bbox(rendered, background)
    assert bbox is not None
    left, top, right, bottom = bbox
    assert left >= 140
    assert top >= 85
    assert TARGET_SIZE[0] - right >= 140
    assert TARGET_SIZE[1] - bottom >= 85


def test_dense_studio_logo_is_reduced_inside_safe_area():
    source = Image.new("RGBA", (600, 240), (0, 0, 0, 0))
    ImageDraw.Draw(source).rectangle((1, 1, 598, 238), fill=(205, 30, 70, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    background = rendered.getpixel((0, 0))[:3]
    bbox = _mark_bbox(rendered, background)
    assert bbox is not None
    left, top, right, bottom = bbox
    assert right - left <= 520
    assert bottom - top <= 180


def test_opaque_white_tpdb_background_is_removed_before_contrast_analysis():
    source = Image.new("RGBA", (420, 180), (255, 255, 255, 255))
    draw = ImageDraw.Draw(source)
    draw.rectangle((55, 50, 170, 130), fill=(10, 10, 10, 255))
    draw.rectangle((250, 50, 365, 130), fill=(10, 10, 10, 255))

    trimmed = trim_logo_whitespace(source).convert("RGBA")
    center = trimmed.getpixel((trimmed.width // 2, trimmed.height // 2))

    assert center[3] == 0

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    r, g, b, a = rendered.getpixel((0, 0))
    assert a == 255
    assert min(r, g, b) >= 225


def test_opaque_dark_tpdb_background_is_removed_before_contrast_analysis():
    source = Image.new("RGBA", (420, 180), (18, 18, 20, 255))
    draw = ImageDraw.Draw(source)
    draw.rectangle((55, 50, 170, 130), fill=(248, 248, 248, 255))
    draw.rectangle((250, 50, 365, 130), fill=(248, 248, 248, 255))

    trimmed = trim_logo_whitespace(source).convert("RGBA")
    center = trimmed.getpixel((trimmed.width // 2, trimmed.height // 2))

    assert center[3] == 0

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    r, g, b, a = rendered.getpixel((0, 0))
    assert a == 255
    assert max(r, g, b) <= 45


def test_dark_studio_logo_gets_light_background():
    source = Image.new("RGBA", (320, 120), (0, 0, 0, 0))
    ImageDraw.Draw(source).rounded_rectangle((20, 20, 300, 100), radius=12, fill=(8, 8, 8, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    r, g, b, a = rendered.getpixel((0, 0))

    assert a == 255
    assert min(r, g, b) >= 225


def test_light_studio_logo_gets_dark_background():
    source = Image.new("RGBA", (320, 120), (0, 0, 0, 0))
    ImageDraw.Draw(source).rounded_rectangle((20, 20, 300, 100), radius=12, fill=(248, 248, 248, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    r, g, b, a = rendered.getpixel((0, 0))

    assert a == 255
    assert max(r, g, b) <= 45


def test_studio_cards_always_request_standardized_tpdb_artwork():
    override_path = ROOT / "frontend" / "studio_art_overrides.js"
    assert override_path.exists()
    source = override_path.read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")

    assert "let renderImg=type==='studios'||!!img" in source
    assert "STUDIO_ART_HTTP_VERSION='v5'" in source
    assert "studioArtUrl=function(id)" in source
    assert "?v=${STUDIO_ART_HTTP_VERSION}" in source
    assert "let logo=id?`<span class=\"studio-logo\"><img src=\"${studioArtUrl(id)}\"" in source
    assert "type==='studios'?studioArtUrl(id):img" in source
    assert "/api/artwork/studios/${encodeURIComponent(id)}?size=card" not in source
    assert "renderImg?`<img" in source
    assert ".studio-card .media-poster{aspect-ratio:16/7" in css
    assert ".studio-card .media-poster img{object-fit:contain" in css


def test_studio_art_override_is_loaded_and_packaged():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert '<script src="/studio_art_overrides.js"></script>' in index
    assert "COPY frontend/studio_art_overrides.js /usr/share/nginx/html/studio_art_overrides.js" in dockerfile


def test_studio_art_route_uses_tpdb_logo_then_poster_fallback():
    routes = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    start = routes.index('@app.get("/api/artwork/studios/{identifier}")')
    end = routes.index("\n\n@app.", start + 10)
    block = routes[start:end]

    assert "local.logo_url if local else None" in block
    assert "local.poster_url if local else None" in block
    assert block.index("local.logo_url if local else None") < block.index("local.poster_url if local else None")
    assert "studio = await tpdb.get_studio(identifier)" in block
    assert "urls = [value for value in (studio.logo_url, studio.poster_url) if value]" in block


def test_studio_art_cache_is_versioned_for_background_removal_and_safe_area():
    source = (ROOT / "scarletx" / "studio_art.py").read_text(encoding="utf-8")
    assert 'STUDIO_ART_CACHE_VERSION = "v5"' in source
    assert 'f"{STUDIO_ART_CACHE_VERSION}-{identifier}.png"' in source


def _mark_bbox(image: Image.Image, background: tuple[int, int, int]):
    diff = Image.new("L", image.size)
    pixels = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    diff.putdata(
        [
            max(abs(r - background[0]), abs(g - background[1]), abs(b - background[2]))
            for r, g, b, _a in pixels
        ]
    )
    return diff.point(lambda p: 255 if p > 24 else 0).getbbox()


def _png(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()
