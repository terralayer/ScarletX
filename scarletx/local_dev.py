from __future__ import annotations

import re
from pathlib import Path

from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .app import app


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


@app.get("/", include_in_schema=False)
def local_frontend_index() -> HTMLResponse:
    """Serve the current source frontend for the local Mac/Python launcher."""
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "</head>",
        '<link rel="stylesheet" href="/auth.css"></head>',
        1,
    )
    html = re.sub(
        r"(<body[^>]*>)",
        r'\1<script src="/auth.js"></script>',
        html,
        count=1,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/app.js", include_in_schema=False)
def local_frontend_app_js() -> Response:
    """Mirror the web-image auth boot transform without creating a stale web copy."""
    source = (FRONTEND / "app.js").read_text(encoding="utf-8")
    source = re.sub(
        r"(?m)^boot\(\);\s*$",
        "authGateBoot(boot);",
        source,
        count=1,
    )
    return Response(
        source,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


# API/auth routes were registered before this mount, so they retain priority.
# Everything else comes directly from the checked-out frontend source tree.
app.mount(
    "/",
    StaticFiles(directory=str(FRONTEND), html=True),
    name="local-frontend",
)
