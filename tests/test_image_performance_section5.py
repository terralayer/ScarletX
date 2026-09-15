from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image


@pytest.mark.asyncio
async def test_card_thumbnail_is_bounded_webp_and_persists_without_source(tmp_path, monkeypatch):
    from scarletx import remote_art

    monkeypatch.setattr(remote_art, "CACHE_ROOT", tmp_path / "images")
    key = "section-5-card"
    source = BytesIO()
    Image.new("RGB", (1600, 1200), (120, 80, 40)).save(source, "JPEG", quality=90)
    remote_art.cache_remote_image_bytes(key, source.getvalue(), "image/jpeg")

    payload, content_type = await remote_art.cached_remote_thumbnail(
        key,
        [],
        (320, 180),
    )
    assert content_type == "image/webp"
    assert len(payload) < len(source.getvalue())
    with Image.open(BytesIO(payload)) as image:
        assert image.size == (320, 180)
        assert image.format == "WEBP"

    data_path, meta_path = remote_art._paths(key)
    data_path.unlink()
    meta_path.unlink(missing_ok=True)

    cached, cached_type = await remote_art.cached_remote_thumbnail(key, [], (320, 180))
    assert cached_type == "image/webp"
    assert cached == payload
