from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

import httpx
from PIL import Image, ImageChops, ImageFilter, ImageOps

TARGET_SIZE = (800, 350)  # 16:7, matching the ScarletX studio cards/detail panel.
MAX_IMAGE_BYTES = 12 * 1024 * 1024
STUDIO_ART_CACHE_VERSION = "v4"
LIGHT_CANVAS = (244, 244, 245, 255)
DARK_CANVAS = (24, 24, 27, 255)
LOGO_MAX_WIDTH_RATIO = 0.72
LOGO_MAX_HEIGHT_RATIO = 0.58
_ART_CACHE: dict[str, bytes] = {}
_ART_CACHE_DIR = Path(os.getenv("SCARLETX_CACHE_DIR", "./cache")).expanduser() / "tpdb" / "studios"


class StudioArtworkError(RuntimeError):
    pass


def _cache_path(identifier: str) -> Path:
    return _ART_CACHE_DIR / f"{STUDIO_ART_CACHE_VERSION}-{identifier}.png"


def cached_studio_artwork(identifier: str) -> bytes | None:
    if identifier in _ART_CACHE:
        return _ART_CACHE[identifier]
    path = _cache_path(identifier)
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
        path = _cache_path(identifier)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(image)
        temp.replace(path)
    except OSError:
        pass


def _edge_pixels(image: Image.Image) -> list[tuple[int, int, int]]:
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
    return pixels


def _edge_background(image: Image.Image) -> tuple[int, int, int]:
    pixels = _edge_pixels(image)
    if not pixels:
        return (255, 255, 255)
    channels = list(zip(*pixels, strict=False))
    ordered = [sorted(channel) for channel in channels]
    midpoint = len(pixels) // 2
    return tuple(int(channel[midpoint]) for channel in ordered)


def _max_rgb_difference(image: Image.Image, background_rgb: tuple[int, int, int]) -> Image.Image:
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, background_rgb)
    red, green, blue = ImageChops.difference(rgb, background).split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


def _has_uniform_edge_background(image: Image.Image, background_rgb: tuple[int, int, int]) -> bool:
    pixels = _edge_pixels(image)
    if not pixels:
        return False
    close = 0
    for red, green, blue in pixels:
        distance = max(
            abs(red - background_rgb[0]),
            abs(green - background_rgb[1]),
            abs(blue - background_rgb[2]),
        )
        if distance <= 18:
            close += 1
    return (close / len(pixels)) >= 0.85


def _remove_uniform_edge_background(image: Image.Image) -> Image.Image:
    """Turn a flat TPDB logo canvas into alpha so only the actual brand mark remains."""
    rgba = image.convert("RGBA")
    background_rgb = _edge_background(rgba)
    if not _has_uniform_edge_background(rgba, background_rgb):
        return rgba

    distance = _max_rgb_difference(rgba, background_rgb)

    # Keep antialiased logo edges while removing near-identical canvas pixels.
    # A short ramp avoids the jagged edge that a hard binary threshold creates.
    foreground_alpha = distance.point(
        lambda value: 0
        if value <= 8
        else 255
        if value >= 28
        else int(round(((value - 8) / 20) * 255))
    ).filter(ImageFilter.MaxFilter(3))

    rgba.putalpha(foreground_alpha)
    bbox = foreground_alpha.point(lambda value: 255 if value > 12 else 0).getbbox()
    if bbox:
        candidate = rgba.crop(bbox)
        if candidate.width >= 8 and candidate.height >= 8:
            return candidate
    return rgba


def trim_logo_whitespace(image: Image.Image) -> Image.Image:
    """Isolate the actual logo mark from transparent or uniform TPDB canvas padding."""
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    had_transparency = alpha.getextrema()[0] < 250

    # If TPDB already supplied real transparency, trust it. Cropping by alpha is
    # sufficient and avoids mistaking a single-color logo edge for a flat canvas.
    if had_transparency:
        bbox = alpha.point(lambda value: 255 if value > 12 else 0).getbbox()
        if bbox:
            rgba = rgba.crop(bbox)
        return rgba

    # Fully opaque TPDB logo images often arrive on white, black, or another flat
    # rectangular canvas. Remove that canvas before contrast scoring and sizing.
    stripped = _remove_uniform_edge_background(rgba)
    if stripped.getchannel("A").getextrema()[0] < 250:
        return stripped

    # Non-uniform opaque images (for example poster fallback art) still benefit
    # from conservative outer-padding trimming without background deletion.
    rgb = rgba.convert("RGB")
    background_rgb = _edge_background(rgb)
    mask = _max_rgb_difference(rgb, background_rgb).point(
        lambda value: 255 if value > 14 else 0
    ).filter(ImageFilter.MaxFilter(3))
    bbox = mask.getbbox()
    if bbox:
        candidate = rgba.crop(bbox)
        if candidate.width >= 8 and candidate.height >= 8:
            rgba = candidate
    return rgba


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    channels: list[float] = []
    for value in rgb:
        component = value / 255.0
        channels.append(component / 12.92 if component <= 0.04045 else ((component + 0.055) / 1.055) ** 2.4)
    return (0.2126 * channels[0]) + (0.7152 * channels[1]) + (0.0722 * channels[2])


def _contrast_ratio(foreground_luminance: float, background_luminance: float) -> float:
    lighter = max(foreground_luminance, background_luminance)
    darker = min(foreground_luminance, background_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def _choose_contrast_canvas(logo: Image.Image) -> tuple[int, int, int, int]:
    """Choose the neutral canvas that best preserves visibility of the logo's real colors."""
    sample = logo.convert("RGBA").copy()
    sample.thumbnail((128, 128), Image.Resampling.LANCZOS)
    pixels = sample.get_flattened_data() if hasattr(sample, "get_flattened_data") else sample.getdata()
    visible = [(r, g, b, a) for r, g, b, a in pixels if a >= 48]
    if not visible:
        return LIGHT_CANVAS

    def score(canvas: tuple[int, int, int, int]) -> float:
        bg_luminance = _relative_luminance(canvas[:3])
        weighted_total = 0.0
        alpha_total = 0.0
        for r, g, b, alpha_value in visible:
            weight = alpha_value / 255.0
            weighted_total += _contrast_ratio(_relative_luminance((r, g, b)), bg_luminance) * weight
            alpha_total += weight
        return weighted_total / max(alpha_total, 1e-9)

    light_score = score(LIGHT_CANVAS)
    dark_score = score(DARK_CANVAS)
    return LIGHT_CANVAS if light_score >= dark_score else DARK_CANVAS


def _add_logo_halo(rendered: Image.Image, logo_layer: Image.Image, canvas: tuple[int, int, int, int]) -> None:
    """Add subtle outer separation without changing any pixels inside the brand mark."""
    mask = logo_layer.getchannel("A")
    blur_radius = max(2.0, min(rendered.size) * 0.012)
    expanded = mask.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    outer = ImageChops.subtract(expanded, mask).point(lambda value: int(value * 0.34))
    halo_rgb = (18, 18, 20) if canvas == LIGHT_CANVAS else (250, 250, 250)
    halo = Image.new("RGBA", rendered.size, (*halo_rgb, 0))
    halo.putalpha(outer)
    rendered.alpha_composite(halo)


def prepare_studio_artwork(image_bytes: bytes, target_size: tuple[int, int] = TARGET_SIZE) -> bytes:
    try:
        source = Image.open(BytesIO(image_bytes))
        source.load()
    except Exception as exc:  # Pillow raises several format-specific exceptions.
        raise StudioArtworkError("Studio artwork is not a readable image") from exc

    logo = trim_logo_whitespace(source).convert("RGBA")
    target_w, target_h = target_size
    inner_size = (
        max(1, int(round(target_w * LOGO_MAX_WIDTH_RATIO))),
        max(1, int(round(target_h * LOGO_MAX_HEIGHT_RATIO))),
    )

    # Fit the actual isolated brand mark into a consistent safe area. This keeps
    # wide and square studio logos visually balanced instead of filling the card.
    fitted = ImageOps.contain(logo, inner_size, method=Image.Resampling.LANCZOS)
    x = (target_w - fitted.width) // 2
    y = (target_h - fitted.height) // 2
    logo_layer = Image.new("RGBA", target_size, (0, 0, 0, 0))
    logo_layer.alpha_composite(fitted, (x, y))

    canvas = _choose_contrast_canvas(fitted)
    rendered = Image.new("RGBA", target_size, canvas)
    _add_logo_halo(rendered, logo_layer, canvas)
    rendered.alpha_composite(logo_layer)

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
