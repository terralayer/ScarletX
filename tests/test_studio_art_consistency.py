from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from scarletx import studio_art
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


def test_neutral_fallback_logo_gets_a_stable_pastel_accent():
    source = Image.new("RGBA", (320, 120), (0, 0, 0, 0))
    ImageDraw.Draw(source).rounded_rectangle((20, 20, 300, 100), radius=12, fill=(8, 8, 8, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source), color_seed="studio-42"))).convert("RGBA")
    red, green, blue, alpha = rendered.getpixel((0, 0))

    assert alpha == 255
    assert max(red, green, blue) - min(red, green, blue) >= 12
    assert min(red, green, blue) >= 130


def test_colored_studio_logo_gets_a_readable_pastel_canvas():
    source = Image.new("RGBA", (320, 120), (0, 0, 0, 0))
    ImageDraw.Draw(source).rounded_rectangle((20, 20, 300, 100), radius=12, fill=(220, 20, 60, 255))

    rendered = Image.open(BytesIO(prepare_studio_artwork(_png(source)))).convert("RGBA")
    red, green, blue, alpha = rendered.getpixel((0, 0))

    assert alpha == 255
    assert red > green + 15
    assert red > blue + 8
    assert min(red, green, blue) >= 130


def test_legacy_studio_artwork_remains_available_when_the_source_logo_is_gone():
    with TemporaryDirectory() as temp_dir:
        original_dir = studio_art._ART_CACHE_DIR
        studio_art._ART_CACHE_DIR = Path(temp_dir)
        try:
            legacy = b"previously-prepared-artwork"
            (studio_art._ART_CACHE_DIR / "v5-studio.png").write_bytes(legacy)
            assert studio_art.legacy_studio_artwork("studio") == legacy
        finally:
            studio_art._ART_CACHE_DIR = original_dir


def test_studio_art_override_only_versions_artwork_and_does_not_replace_core_renderers():
    override_path = ROOT / "frontend" / "studio_art_overrides.js"
    source = override_path.read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")
    assert "STUDIO_ART_HTTP_VERSION='v7'" in source
    assert "studioArtUrl=function(id)" in source
    assert "?v=${STUDIO_ART_HTTP_VERSION}" in source
    assert "studioLink=function" not in source
    assert "entityCard=function" not in source
    assert ".studio-card .media-poster{aspect-ratio:16/7" in css
    assert ".studio-card .media-poster img{object-fit:contain" in css


def test_studio_cards_request_the_current_versioned_artwork():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    card = source[source.index("function entityCard"):source.index("function bindEntityActions")]

    assert "type==='studios'?studioArtUrl(id)" in card
    assert "?v=v5" not in card


def test_small_studio_logos_use_prepared_artwork_background_without_forcing_gray():
    source = (ROOT / "frontend" / "studio_art_overrides.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "ui_overrides.css").read_text(encoding="utf-8")

    assert "studioArtUrl=function(id)" in source
    assert ".studio-logo{" in css
    studio_logo_css = css[css.index(".studio-logo{"):css.index(".studio-logo img{")]
    assert "background:transparent" in studio_logo_css
    assert "background:#f4f4f5" not in studio_logo_css


def test_studio_art_override_is_loaded_and_packaged():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    assert '<script src="/studio_art_overrides.js"></script>' in index
    assert "COPY frontend/studio_art_overrides.js /usr/share/nginx/html/studio_art_overrides.js" in dockerfile


def test_studio_art_route_uses_tpdb_logo_then_poster_fallback(tmp_path, monkeypatch):
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from scarletx.config import Settings
    from scarletx.db import Base
    from scarletx.models import Studio
    from scarletx.routes import application

    engine = create_engine(f'sqlite:///{tmp_path / "art.db"}')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(Studio(tpdb_id='site', name='Site', logo_url='https://example.test/logo.png',
                      poster_url='https://example.test/poster.png'))
        db.commit()
    received = []
    async def download(urls, **kwargs):
        received.extend(urls)
        return b'prepared-image'
    monkeypatch.setattr(application, 'cached_studio_artwork', lambda _: None)
    monkeypatch.setattr(application, 'legacy_studio_artwork', lambda _: None)
    monkeypatch.setattr(application, 'cache_studio_artwork', lambda *_: None)
    monkeypatch.setattr(application, 'download_and_prepare_studio_artwork', download)
    try:
        with sessions() as db:
            response = asyncio.run(application.studio_artwork('site', size='full', db=db, settings=Settings()))
        assert response.body == b'prepared-image'
        assert received == ['https://example.test/logo.png', 'https://example.test/poster.png']
    finally:
        engine.dispose()


def test_studio_art_cache_is_versioned_for_background_removal_and_safe_area():
    source = (ROOT / "scarletx" / "studio_art.py").read_text(encoding="utf-8")
    assert 'STUDIO_ART_CACHE_VERSION = "v7"' in source
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
