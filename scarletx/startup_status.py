from __future__ import annotations

import asyncio

from .config import Settings
from .db import SessionLocal
from .status_console import collect_startup_status, emit_status, render_dashboard


def _render_startup_status(settings: Settings) -> None:
    with SessionLocal() as db:
        try:
            print(render_dashboard(collect_startup_status(db, settings), version="0.4.5"), flush=True)
        except Exception as exc:
            emit_status("Status Console", "FAILED", exc.__class__.__name__, severity="error")


async def emit_startup_status_snapshot(settings: Settings) -> None:
    """Render the read-only startup snapshot without blocking application startup."""
    await asyncio.to_thread(_render_startup_status, settings)
