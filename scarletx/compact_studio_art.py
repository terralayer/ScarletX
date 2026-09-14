from __future__ import annotations

from io import BytesIO

from fastapi import Depends
from fastapi.responses import Response
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from .config import Settings
from .db import get_session
from .routes import application as legacy_application
from .studio_art import trim_logo_whitespace

COMPACT_STUDIO_SIZE = (320, 140)
COMPACT_STUDIO_MAX = (286, 112)


def prepare_compact_studio_artwork(image_bytes: bytes, target_size: tuple[int, int] = COMPACT_STUDIO_SIZE) -> bytes:
    source = Image.open(BytesIO(image_bytes)).convert("RGBA")
    logo = trim_logo_whitespace(source).convert("RGBA")
    fitted = ImageOps.contain(logo, COMPACT_STUDIO_MAX, method=Image.Resampling.LANCZOS)
    rendered = Image.new("RGBA", target_size, (0, 0, 0, 0))
    x = (target_size[0] - fitted.width) // 2
    y = (target_size[1] - fitted.height) // 2
    rendered.alpha_composite(fitted, (x, y))
    out = BytesIO()
    rendered.save(out, "PNG", optimize=True)
    return out.getvalue()


async def compact_studio_artwork(
    identifier: str,
    db: Session = Depends(get_session),
    settings: Settings = Depends(legacy_application.get_runtime_settings),
):
    prepared = await legacy_application.studio_artwork(
        identifier=identifier,
        size="full",
        db=db,
        settings=settings,
    )
    body = bytes(getattr(prepared, "body", b""))
    compact = prepare_compact_studio_artwork(body)
    return Response(
        content=compact,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


def install_compact_studio_art_route(app) -> None:
    path = "/api/artwork/studios/{identifier}/compact"
    if any(getattr(route, "path", None) == path for route in app.router.routes):
        return
    app.add_api_route(
        path,
        compact_studio_artwork,
        methods=["GET"],
        name="compact_studio_artwork",
    )
