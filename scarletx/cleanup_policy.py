from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path


def cleanup_native_staging(
    staging_path: Path,
    *,
    library_path: Path,
    import_succeeded: bool,
) -> bool:
    """Remove ScarletX-owned native staging only after a durable import succeeds."""

    if not import_succeeded:
        return False

    staging = Path(staging_path).expanduser()
    library = Path(library_path).expanduser()
    if not staging.exists() or not staging.is_dir():
        return False

    staging_resolved = staging.resolve()
    library_resolved = library.resolve(strict=False)
    if staging_resolved == Path(staging_resolved.anchor):
        return False
    if library_resolved.is_relative_to(staging_resolved):
        return False

    shutil.rmtree(staging)
    return True


def cleanup_orphan_partials(
    root: Path,
    *,
    older_than: timedelta,
    now: datetime | None = None,
) -> list[Path]:
    """Delete only stale atomic-publish partial files under the supplied root."""

    root = Path(root).expanduser()
    if not root.exists() or not root.is_dir():
        return []

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    cutoff = current - older_than
    removed: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if not path.name.startswith(".") or ".partial-" not in path.name:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified > cutoff:
            continue
        path.unlink()
        removed.append(path)
    return removed
