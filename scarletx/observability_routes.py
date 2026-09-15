from __future__ import annotations

import os
from pathlib import Path
import shutil
import time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import BackgroundJob, NativeUsenetJob, TrackedDownload
from .observability import runtime_observability

router = APIRouter()
_STARTED_AT = time.monotonic()


def _status_counts(db: Session, model) -> dict[str, int]:
    try:
        rows = db.execute(select(model.status, func.count()).group_by(model.status)).all()
        return {str(status or "unknown"): int(count) for status, count in rows}
    except Exception:
        return {}


def _active_speed_bps(db: Session) -> float:
    try:
        value = db.scalar(
            select(func.coalesce(func.sum(NativeUsenetJob.speed_bps), 0.0)).where(
                NativeUsenetJob.status == "downloading"
            )
        )
        return float(value or 0.0)
    except Exception:
        return 0.0


def _rss_bytes() -> int | None:
    try:
        resident_pages = int(Path("/proc/self/statm").read_text(encoding="utf-8").split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        return None


def _disk_snapshot() -> dict[str, int | None]:
    configured = os.getenv("SCARLETX_CONFIG_DIR") or os.getenv("SCARLETX_DATA_DIR") or "."
    path = Path(configured).expanduser()
    if not path.exists():
        path = Path(".")
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
        }
    except Exception:
        return {"total_bytes": None, "used_bytes": None, "free_bytes": None}


@router.get("/api/system/metrics")
def system_metrics(db: Session = Depends(get_session)) -> dict[str, object]:
    """Return a low-overhead runtime snapshot on demand.

    Operational database aggregates are evaluated only when this endpoint is
    requested. No request payloads, SQL text, NZB URLs, or credentials are
    included in the response.
    """

    snapshot = runtime_observability.snapshot()
    native = _status_counts(db, NativeUsenetJob)
    background = _status_counts(db, BackgroundJob)
    tracked = _status_counts(db, TrackedDownload)

    pending_imports = (
        native.get("completed", 0)
        + native.get("downloaded", 0)
        + tracked.get("completed", 0)
        + tracked.get("downloaded", 0)
    )

    snapshot.update(
        {
            "queues": {
                "native": native,
                "background": background,
                "tracked": tracked,
            },
            "downloads": {
                "active": native.get("downloading", 0),
                "active_speed_bps": _active_speed_bps(db),
            },
            "imports": {
                "pending": pending_imports,
                "failed": tracked.get("failed", 0),
            },
            "process": {
                "uptime_seconds": round(max(0.0, time.monotonic() - _STARTED_AT), 3),
                "cpu_seconds": round(max(0.0, time.process_time()), 3),
                "rss_bytes": _rss_bytes(),
            },
            "disk": _disk_snapshot(),
        }
    )
    return snapshot
