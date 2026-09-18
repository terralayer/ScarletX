from __future__ import annotations

import asyncio
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from uuid import uuid4
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
_ART_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="scarletx-art")
_INFLIGHT: dict[tuple, asyncio.Task] = {}


async def run_artwork_work(function, *args, **kwargs):
    return await asyncio.get_running_loop().run_in_executor(_ART_WORKERS, partial(function, *args, **kwargs))


async def _shared_job(key: tuple, factory):
    # Jobs belong to their event loop; completed jobs never become an unbounded cache.
    flight_key = (asyncio.get_running_loop(), str(CACHE_ROOT), *key)
    task = _INFLIGHT.get(flight_key)
    if task is None:
        task = asyncio.create_task(factory())
        _INFLIGHT[flight_key] = task

        def finished(done):
            if _INFLIGHT.get(flight_key) is done:
                _INFLIGHT.pop(flight_key, None)
            if not done.cancelled():
                done.exception()  # Retrieve failures even when every waiter disconnected.

        task.add_done_callback(finished)
    # One disconnected browser must not cancel work shared with another browser.
    return await asyncio.shield(task)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp.write_bytes(payload)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)



def _art_client() -> httpx.AsyncClient:
    global _ART_CLIENT
    if _ART_CLIENT is None or _ART_CLIENT.is_closed:
        _ART_CLIENT = httpx.AsyncClient(
            timeout=12,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": "ScarletX/0.4.9"},
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


def _thumb_path(key: str, size: tuple[int, int], *, contain: bool = False) -> Path:
    digest = hashlib.sha256(f"{key}:{size[0]}x{size[1]}:{contain}:webp-v2".encode()).hexdigest()
    return CACHE_ROOT / "thumbs" / f"{digest}.webp"


def cache_remote_image_bytes(
    key: str,
    content: bytes,
    content_type: str,
    source_url: str | None = None,
) -> None:
    """Seed a route cache key from bytes already fetched during import."""
    data_path, meta_path = _paths(key)
    try:
        _atomic_write(data_path, content)
        _atomic_write(meta_path, json.dumps({"content_type": content_type or "image/jpeg", "url": source_url or ""}).encode())
    except OSError:
        pass


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


def _read_original(key: str) -> tuple[bytes, str] | None:
    data_path, meta_path = _paths(key)
    try:
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return data_path.read_bytes(), str(meta.get("content_type") or "image/jpeg")
    except (OSError, json.JSONDecodeError):
        return None


async def _load_original(key: str, urls: list[str]) -> tuple[bytes, str]:
    cached = await run_artwork_work(_read_original, key)
    if cached is not None:
        return cached
    last_error = None
    client = _art_client()
    for url in urls:
        if not url:
            continue
        try:
            content, ctype, final_url = await _download_public_image(client, str(url))
            await run_artwork_work(cache_remote_image_bytes, key, content, ctype, final_url)
            return content, ctype
        except (httpx.HTTPError, OSError, RemoteArtworkError) as exc:
            last_error = exc
    raise RemoteArtworkError("Remote artwork could not be loaded") from last_error


async def cached_remote_image(key: str, urls: list[str]) -> tuple[bytes, str]:
    return await _shared_job(("original", key), lambda: _load_original(key, urls))


def _read_thumbnail(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _render_thumbnail(original: bytes, path: Path, size: tuple[int, int], contain: bool) -> bytes:
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
        _atomic_write(path, payload)
    except OSError:
        pass
    return payload


async def _load_thumbnail(key: str, urls: list[str], size: tuple[int, int], contain: bool) -> tuple[bytes, str]:
    path = _thumb_path(key, size, contain=contain)
    cached = await run_artwork_work(_read_thumbnail, path)
    if cached is not None:
        return cached, "image/webp"
    original, _ = await cached_remote_image(key, urls)
    payload = await run_artwork_work(_render_thumbnail, original, path, size, contain)
    return payload, "image/webp"


async def cached_remote_thumbnail(key: str, urls: list[str], size: tuple[int, int], *, contain: bool = False) -> tuple[bytes, str]:
    """Share concurrent requests for the same persistent thumbnail variant."""
    return await _shared_job(("thumbnail", key, size, contain), lambda: _load_thumbnail(key, urls, size, contain))
