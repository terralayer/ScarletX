from __future__ import annotations

import re

MIN_RELEASE_BYTES = 500 * 1024 * 1024

_REJECTED_TITLE_TOKENS = {
    "sample",
    "trailer",
    "image",
    "images",
    "photo",
    "photos",
    "picture",
    "pictures",
    "gallery",
    "screenshot",
    "screenshots",
}
_IMAGE_EXTENSIONS = {"bmp", "gif", "heic", "jpeg", "jpg", "png", "tif", "tiff", "webp"}


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def release_rejection_reason(title: str, size: int | None) -> str | None:
    if size is not None and int(size) < MIN_RELEASE_BYTES:
        return "Release is smaller than 500 MiB"
    if _tokens(title) & _REJECTED_TITLE_TOKENS:
        return "Release title identifies sample or image content"
    return None


def payload_name_is_ignored(value: str) -> bool:
    tokens = _tokens(value)
    if tokens & {"sample", "trailer"}:
        return True
    return bool(tokens & _IMAGE_EXTENSIONS)
