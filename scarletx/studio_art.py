from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageFilter, ImageOps

TARGET_SIZE = (800, 350)  # 16:7, matching the ScarletX studio cards/detail panel.
MAX_IMAGE_BYTES = 12 * 1024 * 1024
_ART_CACHE: dict[str, bytes] = {}
_ART_CACHE_DIR = Path(os.getenv("SCARLETX_CACHE_DIR", "./cache")).expanduser() / "tpdb" / "studios"


class StudioArtworkError(RuntimeError):
    pass


def cached_studio_artwork(identifier: str) -> bytes | None:
    if identifier in _ART_CACHE:
        return _ART_CACHE[identifier]
    path = _ART_CACHE_DIR / f"{identifier}.png"
    try:
        if path.exists():
            data = path.read_bytes()
            _ART_CACHE[identifier] = data
            return data
    except OSError:
        pass
    return None


def cache_studio_artwork(identifier: str, image: bytes) -> None:
    # Keep the dev UI responsive without repeatedly hitting TPDB/CDN for every render.
    if len(_ART_CACHE) >= 512:
        _ART_CACHE.pop(next(iter(_ART_CACHE)))
    _ART_CACHE[identifier] = image
    try:
        _ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _ART_CACHE_DIR / f"{identifier}.png"
        temp = path.with_suffix(".tmp")
        temp.write_bytes(image); temp.replace(path)
    except OSError:
        pass


def _edge_background(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    w, h = rgb.size
    band = max(1, min(w, h) // 60)
    pixels: list[tuple[int, int, int]] = []
    for strip in (
        rgb.crop((0, 0, w, band)),
        rgb.crop((0, h - band, w, h)),
        rgb.crop((0, 0, band, h)),
        rgb.crop((w - band, 0, w, h)),
    ):
        pixels.extend(strip.get_flattened_data() if hasattr(strip, "get_flattened_data") else strip.getdata())
    if not pixels:
        return (255, 255, 255)
    channels = list(zip(*pixels, strict=False))
    ordered = [sorted(channel) for channel in channels]
    midpoint = len(pixels) // 2
    return tuple(int(channel[midpoint]) for channel in ordered)


def trim_logo_whitespace(image: Image.Image) -> Image.Image:
    """Trim transparent or near-uniform outer padding without erasing logo detail."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 250:
        bbox = alpha.point(lambda p: 255 if p > 12 else 0).getbbox()
        if bbox:
            rgba = rgba.crop(bbox)

    rgb = rgba.convert("RGB")
    bg = _edge_background(rgb)
    background = Image.new("RGB", rgb.size, bg)
    diff = ImageChops.difference(rgb, background)
    # MaxFilter retains antialiased logo edges while ignoring near-identical padding.
    mask = diff.convert("L").point(lambda p: 255 if p > 14 else 0).filter(ImageFilter.MaxFilter(3))
    bbox = mask.getbbox()
    if bbox:
        candidate = rgba.crop(bbox)
        # Ignore pathological trims that would collapse almost the entire image.
        if candidate.width >= 8 and candidate.height >= 8:
            rgba = candidate
    return rgba


def prepare_studio_artwork(image_bytes: bytes, target_size: tuple[int, int] = TARGET_SIZE) -> bytes:
    try:
        source = Image.open(BytesIO(image_bytes))
        source.load()
    except Exception as exc:  # Pillow raises several format-specific exceptions.
        raise StudioArtworkError("Studio artwork is not a readable image") from exc

    logo = trim_logo_whitespace(source)
    target_w, target_h = target_size
    target_ratio = target_w / target_h
    ratio = logo.width / max(logo.height, 1)

    # Ordinary horizontal/square-ish logos can be safely filled. Very wide/tall marks
    # are contained so the full logo remains visible, per the requested fallback rule.
    if 1.45 <= ratio <= 3.4:
        rendered = ImageOps.fit(
            logo.convert("RGBA"),
            target_size,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    else:
        rendered = Image.new("RGBA", target_size, (0, 0, 0, 0))
        fitted = ImageOps.contain(logo.convert("RGBA"), target_size, method=Image.Resampling.LANCZOS)
        rendered.alpha_composite(fitted, ((target_w - fitted.width) // 2, (target_h - fitted.height) // 2))

    out = BytesIO()
    rendered.save(out, "PNG", optimize=True)
    return out.getvalue()


async def download_and_prepare_studio_artwork(urls: list[str]) -> bytes:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, trust_env=False) as client:
        last_error: Exception | None = None
        for url in urls:
            if not url or not url.lower().startswith(("https://", "http://")):
                continue
            try:
                response = await client.get(url)
                response.raise_for_status()
                content = response.content
                if len(content) > MAX_IMAGE_BYTES:
                    raise StudioArtworkError("Studio artwork is too large")
                return prepare_studio_artwork(content)
            except (httpx.HTTPError, StudioArtworkError) as exc:
                last_error = exc
        raise StudioArtworkError("Studio artwork could not be loaded") from last_error
