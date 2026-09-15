from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiskCapacityDecision:
    allowed: bool
    free_bytes: int
    required_bytes: int
    reserve_bytes: int
    available_after_required: int
    reason: str | None = None


def _existing_disk_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def check_disk_capacity(
    path: str | Path,
    *,
    required_bytes: int = 0,
    reserve_bytes: int = 0,
) -> DiskCapacityDecision:
    """Check whether work fits while preserving a configured disk reserve."""

    required = max(0, int(required_bytes or 0))
    reserve = max(0, int(reserve_bytes or 0))
    free = max(0, int(shutil.disk_usage(_existing_disk_path(path)).free))
    after_required = max(0, free - required)
    allowed = free >= required and after_required >= reserve
    return DiskCapacityDecision(
        allowed=allowed,
        free_bytes=free,
        required_bytes=required,
        reserve_bytes=reserve,
        available_after_required=after_required,
        reason=None if allowed else "free_space_reserve",
    )
