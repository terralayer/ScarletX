from __future__ import annotations

import asyncio
import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin

import httpx
from PIL import Image, ImageOps

from .network_security import validate_public_https_url

CACHE_ROOT = Path(os.getenv("SCARLETX_CACHE_DIR", "./cache")).expanduser() / "tpdb" / "images"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5
_ART_CLIENT: httpx.AsyncClient | None = None


def _art_client() -> httpx.AsyncClient:
    global _ART_CLIENT
    if _ART_CLIENT is None or _ART_CLIENT.is_closed:
        _ART_CLIENT = httpx.AsyncClient(
            timeout=12,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "ScarletX/0.3.9"},
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15, keepalive_expiry=45),
        )
    return _ART_CLIENT


async def close_remote_art_client() -> None:
    global _ART_CLIENT
    client, _ART_CLIENT = _ART_CLIENT, None
    if client is not None and not client.is_closed:
        await client.aclose()


class RemoteArtworkError(RuntimeError):
    pass


def _paths(key: str) -> tuple[Path, Path]:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return CACHE_ROOT / f"{digest}.bin", CACHE_ROOT / f"{digest}.json"


def _thumb_path(key: str, size: tuple[int, int]) -> Path:
    digest = hashlib.sha256(f"{key}:{size[0]}x{size[1]}:webp-v1".encode()).hexdigest()
    return CACHE_ROOT / "thumbs" / f"{digest}.webp"


async def _download_public_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str, str]:
    current = str(url or "").strip()
    for _redirect in range(MAX_REDIRECTS + 1):
        try:
            await asyncio.to_thread(validate_public_https_url, current)
        except ValueError as exc:
            raise RemoteArtworkError(str(exc)) from exc

        async with client.stream("GET", current) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = (response.headers.get("location") or "").strip()
                if not location:
                    raise RemoteArtworkError("Remote artwork redirect had no destination")
                current = urljoin(str(response.url), location)
                continue

            response.raise_for_status()
            ctype = (response.headers.get("content-type") or "image/jpeg").split(";", 1)[0].strip().casefold()
            if not ctype.startswith("image/"):
                raise RemoteArtworkError("Remote artwork was not an image")
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_IMAGE_BYTES:
                        raise RemoteArtworkError("Remote artwork is too large")
                except ValueError:
                    pass

            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > MAX_IMAGE_BYTES:
                    raise RemoteArtworkError("Remote artwork is too large")
                content.extend(chunk)
            return bytes(content), ctype, str(response.url)

    raise RemoteArtworkError("Remote artwork exceeded the redirect limit")


async def cached_remote_image(key: str, urls: list[str]) -> tuple[bytes, str]:
    data_path, meta_path = _paths(key)
    if data_path.exists():
        try:
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            return data_path.read_bytes(), str(meta.get("content_type") or "image/jpeg")
        except (OSError, json.JSONDecodeError):
            pass
    last_error = None
    client = _art_client()
    for url in urls:
        if not url:
            continue
        try:
            content, ctype, final_url = await _download_public_image(client, str(url))
            data_path.parent.mkdir(parents=True, exist_ok=True)
            temp = data_path.with_suffix(".tmp")
            temp.write_bytes(content)
            temp.replace(data_path)
            meta_path.write_text(json.dumps({"content_type": ctype, "url": final_url}))
            return content, ctype
        except (httpx.HTTPError, OSError, RemoteArtworkError) as exc:
            last_error = exc
    raise RemoteArtworkError("Remote artwork could not be loaded") from last_error


async def cached_remote_thumbnail(key: str, urls: list[str], size: tuple[int, int], *, contain: bool = False) -> tuple[bytes, str]:
    """Return a small persistent WebP variant for library cards.

    The original remote image is cached once, then every subsequent library render
    reads the much smaller local WebP instead of decoding/transferring the full TPDB
    artwork again.
    """
    path = _thumb_path(key, size)
    try:
        if path.exists():
            return path.read_bytes(), "image/webp"
    except OSError:
        pass
    original, _ = await cached_remote_image(key, urls)
    try:
        with Image.open(BytesIO(original)) as image:
            image.load()
            if contain:
                rendered = ImageOps.contain(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", size, (250, 250, 250))
                canvas.paste(rendered, ((size[0] - rendered.width) // 2, (size[1] - rendered.height) // 2))
                rendered = canvas
            else:
                rendered = ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)
            out = BytesIO()
            rendered.save(out, "WEBP", quality=82, method=4)
            payload = out.getvalue()
    except Exception as exc:
        raise RemoteArtworkError("Remote artwork could not be resized") from exc
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_bytes(payload)
        temp.replace(path)
    except OSError:
        pass
    return payload, "image/webp"
