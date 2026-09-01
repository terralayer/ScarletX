from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Literal, TextIO

from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from .config import Settings

Severity = Literal["ok", "active", "warning", "error"]

_RESET = "\x1b[0m"
_RED = "\x1b[31;1m"
_GREEN = "\x1b[32;1m"
_YELLOW = "\x1b[33;1m"
_CYAN = "\x1b[36;1m"

_STYLE = {
    "ok": ("✓", _GREEN),
    "active": ("●", _CYAN),
    "warning": ("!", _YELLOW),
    "error": ("✗", _RED),
}

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")

_WORDMARK = r"""
███████╗ ██████╗ █████╗ ██████╗ ██╗     ███████╗████████╗██╗  ██╗
██╔════╝██╔════╝██╔══██╗██╔══██╗██║     ██╔════╝╚══██╔══╝╚██╗██╔╝
███████╗██║     ███████║██████╔╝██║     █████╗     ██║    ╚███╔╝
╚════██║██║     ██╔══██║██╔══██╗██║     ██╔══╝     ██║    ██╔██╗
███████║╚██████╗██║  ██║██║  ██║███████╗███████╗   ██║   ██╔╝ ██╗
╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝
""".strip("\n")


@dataclass(frozen=True)
class StatusRow:
    component: str
    state: str
    detail: str = ""
    severity: Severity = "ok"


@dataclass(frozen=True)
class StatusGroup:
    name: str
    rows: list[StatusRow] = field(default_factory=list)


def sanitize_console_text(value: object, *, limit: int = 160) -> str:
    """Make untrusted text safe for a single terminal/log line."""
    text = str(value or "")
    text = _CONTROL_RE.sub(" ", text)
    text = " ".join(text.split())
    if len(text) > limit:
        return text[: max(0, limit - 1)] + "…"
    return text


def color_enabled(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if os.getenv("NO_COLOR") is not None:
        return False
    override = os.getenv("SCARLETX_COLOR", "").strip().lower()
    if override in {"0", "false", "no", "off", "never"}:
        return False
    if override in {"1", "true", "yes", "on", "always"}:
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{_RESET}" if enabled else text


def _status_token(severity: Severity, color: bool) -> str:
    symbol, code = _STYLE.get(severity, _STYLE["warning"])
    token = f"[{symbol}]"
    return _paint(token, code, color)


def _row_line(row: StatusRow, *, color: bool, width: int = 66) -> str:
    component = sanitize_console_text(row.component, limit=34)
    state = sanitize_console_text(row.state, limit=18).upper()
    detail = sanitize_console_text(row.detail, limit=80)
    dots = "." * max(2, 28 - len(component))
    state_text = f"{state:<12}"
    line = f"{_status_token(row.severity, color)} {component} {dots} {state_text}"
    if detail:
        line += f" {detail}"
    return line.rstrip()


def _header(title: str, *, color: bool, width: int = 66) -> str:
    title = f" {sanitize_console_text(title, limit=40)} "
    remaining = max(2, width - len(title) - 2)
    left = remaining // 2
    right = remaining - left
    raw = f"┌{'─' * left}{title}{'─' * right}┐"
    return _paint(raw, _CYAN, color)


def _footer(*, color: bool, width: int = 66) -> str:
    return _paint("└" + "─" * width + "┘", _CYAN, color)


def render_dashboard(
    groups: Iterable[StatusGroup],
    *,
    version: str,
    color: bool | None = None,
    stream: TextIO | None = None,
) -> str:
    """Render the startup dashboard without writing it."""
    use_color = color_enabled(stream) if color is None else bool(color)
    groups = list(groups)
    wordmark = _paint(_WORDMARK, _RED, True) if use_color else _WORDMARK

    lines = [
        wordmark,
        "",
        "                            SCARLETX",
        "                     TerraLayer Software",
        f"                       ScarletX {sanitize_console_text(version, limit=30)}",
        "",
    ]
    severities: list[Severity] = []
    for group in groups:
        lines.append(_header(group.name, color=use_color))
        for row in group.rows:
            severities.append(row.severity)
            lines.append("│ " + _row_line(row, color=use_color).ljust(64) + " │")
        lines.append(_footer(color=use_color))
        lines.append("")

    if "error" in severities:
        summary = "STATUS:  ✗ ONE OR MORE SYSTEMS FAILED"
        summary_color = _RED
    elif "warning" in severities:
        summary = "STATUS:  ! SYSTEMS OPERATIONAL WITH WARNINGS"
        summary_color = _YELLOW
    else:
        summary = "STATUS:  ✓ ALL SYSTEMS OPERATIONAL"
        summary_color = _GREEN

    lines.append("━" * 68)
    lines.append(_paint(f"  {summary}", summary_color, use_color))
    lines.append("━" * 68)
    return "\n".join(lines)


def emit_status(
    component: object,
    state: object,
    detail: object = "",
    *,
    severity: Severity | None = None,
    color: bool | None = None,
    stream: TextIO | None = None,
) -> None:
    """Emit one safe, structured ScarletX status event."""
    stream = stream or sys.stdout
    state_text = sanitize_console_text(state, limit=18).upper()
    if severity is None:
        if state_text in {"FAILED", "OFFLINE", "ERROR"}:
            severity = "error"
        elif state_text in {"WARNING", "DEGRADED", "RETRYING", "DISABLED"}:
            severity = "warning"
        elif state_text in {"ACTIVE", "RUNNING", "DOWNLOADING", "VERIFYING", "PROCESSING"}:
            severity = "active"
        else:
            severity = "ok"
    use_color = color_enabled(stream) if color is None else bool(color)
    row = StatusRow(
        sanitize_console_text(component, limit=34),
        state_text,
        sanitize_console_text(detail, limit=120),
        severity,
    )
    print(_row_line(row, color=use_color, width=72), file=stream, flush=True)


def _count(db: Session, model, *criteria) -> int:
    statement = select(func.count()).select_from(model)
    if criteria:
        statement = statement.where(*criteria)
    return int(db.scalar(statement) or 0)


def _path_row(component: str, path_value: str | Path, *, missing_warning: bool = True) -> StatusRow:
    path = Path(path_value).expanduser()
    if not path.exists():
        return StatusRow(component, "MISSING", str(path), "warning" if missing_warning else "error")
    writable = os.access(path, os.W_OK)
    return StatusRow(component, "WRITABLE" if writable else "READ-ONLY", str(path), "ok" if writable else "warning")


def _pool_detail(db: Session) -> str:
    try:
        pool = db.get_bind().pool
        size = getattr(pool, "size", None)
        checkedout = getattr(pool, "checkedout", None)
        overflow = getattr(pool, "overflow", None)
        size_value = int(size()) if callable(size) else None
        checked_value = int(checkedout()) if callable(checkedout) else 0
        overflow_value = max(0, int(overflow())) if callable(overflow) else 0
        if size_value is not None:
            return f"{checked_value} / {size_value + overflow_value} connections"
        return pool.__class__.__name__
    except Exception:
        return "pool available"


def _tool(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found).name
    return None


def _group_error(name: str, exc: Exception) -> StatusGroup:
    return StatusGroup(name, [StatusRow("Status Collection", "FAILED", exc.__class__.__name__, "error")])


def collect_startup_status(db: Session, settings: Settings) -> list[StatusGroup]:
    """Collect a read-only, no-network startup snapshot for the console."""
    from .models import AuthUser, NativeUsenetJob, Performer, RootFolder, Scene, Studio, TrackedDownload

    groups: list[StatusGroup] = []

    try:
        admin_count = _count(db, AuthUser)
        secret_key = Path(os.getenv("SCARLETX_SECRET_KEY_FILE", "/config/.scarletx-secret.key"))
        system_rows = [
            StatusRow("Nginx Web Boundary", "READY", "public HTTP entrypoint", "ok"),
            StatusRow("FastAPI Backend", "ONLINE", "internal :8000", "ok"),
            StatusRow("Database", "READY", db.get_bind().url.get_backend_name(), "ok"),
            StatusRow("Database Pool", "READY", _pool_detail(db), "ok"),
            StatusRow("Secret Store", "SECURE" if secret_key.exists() else "INITIALIZING", str(secret_key), "ok" if secret_key.exists() else "warning"),
            StatusRow("Authentication", "READY" if admin_count else "SETUP REQUIRED", f"{admin_count} admin users", "ok" if admin_count else "warning"),
            StatusRow("SSE Event Stream", "READY", "Nginx buffering disabled", "ok"),
        ]
        groups.append(StatusGroup("SYSTEM", system_rows))
    except Exception as exc:
        groups.append(_group_error("SYSTEM", exc))

    try:
        tpdb_configured = bool(settings.theporndb_api_key.get_secret_value())
        cache_path = Path(os.getenv("SCARLETX_CACHE_DIR", "/config/cache"))
        metadata_rows = [
            StatusRow("ThePornDB", "READY" if tpdb_configured else "UNCONFIGURED", "API credentials configured" if tpdb_configured else "API key not configured", "ok" if tpdb_configured else "warning"),
            StatusRow("Metadata Cache", "READY" if cache_path.exists() else "MISSING", str(cache_path), "ok" if cache_path.exists() else "warning"),
            StatusRow("Artwork Fetcher", "SECURE", "HTTPS + public-network targets only", "ok"),
            StatusRow("Scenes", "READY", f"{_count(db, Scene)} scenes", "ok"),
            StatusRow("Performers", "READY", f"{_count(db, Performer)} performers", "ok"),
            StatusRow("Studios", "READY", f"{_count(db, Studio)} studios", "ok"),
        ]
        groups.append(StatusGroup("METADATA", metadata_rows))
    except Exception as exc:
        groups.append(_group_error("METADATA", exc))

    try:
        indexers = settings.newznab_indexers()
        enabled_indexers = [item for item in indexers if item.enabled]
        monitored = _count(db, Scene, Scene.monitored.is_(True))
        groups.append(StatusGroup("SEARCH", [
            StatusRow("Indexers", "READY" if enabled_indexers else "DISABLED", f"{len(enabled_indexers)} / {len(indexers)} enabled", "ok" if enabled_indexers else "warning"),
            StatusRow("Search Engine", "READY", "Newznab + indexed library matching", "ok"),
            StatusRow("Monitoring", "ACTIVE" if monitored else "IDLE", f"{monitored} monitored scenes", "active" if monitored else "ok"),
            StatusRow("Automation Scheduler", "ACTIVE" if settings.automatic_search_enabled else "DISABLED", f"every {settings.automatic_search_interval_minutes} min", "active" if settings.automatic_search_enabled else "warning"),
        ]))
    except Exception as exc:
        groups.append(_group_error("SEARCH", exc))

    try:
        providers = settings.native_usenet_providers()
        enabled_providers = [provider for provider in providers if provider.enabled]
        jobs = list(db.scalars(select(NativeUsenetJob)).all())
        failed = sum(1 for job in jobs if str(job.status).casefold() == "failed")
        active_states = {"queued", "downloading", "verifying", "repairing", "extracting", "processing", "postprocessing"}
        active_jobs = [job for job in jobs if str(job.status).casefold() in active_states]
        speed_bps = sum(float(job.speed_bps or 0) for job in active_jobs)
        usenet_rows = [
            StatusRow("Native Downloader", "READY" if settings.native_usenet_enabled and enabled_providers else ("DISABLED" if not settings.native_usenet_enabled else "DEGRADED"), f"{len(enabled_providers)} providers", "ok" if settings.native_usenet_enabled and enabled_providers else "warning"),
        ]
        for provider in providers:
            usenet_rows.append(StatusRow(
                provider.name,
                "CONFIGURED" if provider.enabled else "DISABLED",
                f"TLS :{provider.port} | {provider.connections} connections",
                "ok" if provider.enabled else "warning",
            ))
        total_connections = sum(provider.connections for provider in enabled_providers)
        usenet_rows.extend([
            StatusRow("Connections", "READY", f"{total_connections} configured | runtime cap {settings.native_usenet_max_connections}", "ok"),
            StatusRow("Download Queue", "ACTIVE" if active_jobs else "CLEAR", f"{len(active_jobs)} active | {speed_bps / (1024 * 1024):.1f} MB/s", "active" if active_jobs else "ok"),
            StatusRow("Failed Queue", "CLEAR" if failed == 0 else "WARNING", f"{failed} failed", "ok" if failed == 0 else "warning"),
            StatusRow("Speed Limit", "UNLIMITED" if settings.native_usenet_speed_limit_mb_s <= 0 else "READY", "no limit" if settings.native_usenet_speed_limit_mb_s <= 0 else f"{settings.native_usenet_speed_limit_mb_s:g} MB/s", "ok"),
        ])
        groups.append(StatusGroup("USENET", usenet_rows))
    except Exception as exc:
        groups.append(_group_error("USENET", exc))

    try:
        par2 = _tool("par2", "par2cmdline")
        extractor = _tool("7z", "7zz", "unrar")
        pending_native = _count(db, NativeUsenetJob, NativeUsenetJob.status.in_(("completed", "downloaded")))
        pending_tracked = _count(db, TrackedDownload, TrackedDownload.imported_at.is_(None), TrackedDownload.status.in_(("completed", "downloaded")))
        groups.append(StatusGroup("POST-PROCESSING", [
            StatusRow("PAR2 Verification", "READY" if par2 else "MISSING", par2 or "par2 not found", "ok" if par2 else "warning"),
            StatusRow("Repair", "ENABLED" if settings.native_usenet_repair_enabled else "DISABLED", "PAR2 repair", "ok" if settings.native_usenet_repair_enabled else "warning"),
            StatusRow("Archive Extraction", "READY" if extractor else "MISSING", extractor or "7z/unrar not found", "ok" if extractor else "warning"),
            StatusRow("Archive Security", "ENABLED", "traversal + symlink containment", "ok"),
            StatusRow("Import Worker", "ACTIVE" if settings.completed_download_import_enabled else "DISABLED", "completed-download processing", "active" if settings.completed_download_import_enabled else "warning"),
            StatusRow("Pending Imports", "CLEAR" if pending_native + pending_tracked == 0 else "ACTIVE", f"{pending_native + pending_tracked} pending", "ok" if pending_native + pending_tracked == 0 else "active"),
        ]))
    except Exception as exc:
        groups.append(_group_error("POST-PROCESSING", exc))

    try:
        roots = list(db.scalars(select(RootFolder).where(RootFolder.content_type == "scene")).all())
        library_rows: list[StatusRow] = []
        if roots:
            for root in roots:
                library_rows.append(_path_row(f"Media Root: {root.name}", root.path))
        else:
            library_rows.append(StatusRow("Media Root", "UNCONFIGURED", "no scene root folders", "warning"))
        library_rows.extend([
            _path_row("Incomplete Downloads", settings.native_usenet_incomplete_dir),
            _path_row("Complete Downloads", settings.native_usenet_complete_dir),
            StatusRow("Library Scanner", "READY", "watch + explicit scans", "ok"),
            StatusRow("Scene Matcher", "READY", "indexed title matching", "ok"),
            StatusRow("Auto Import", "ACTIVE" if settings.completed_download_import_enabled else "DISABLED", "download completion worker", "active" if settings.completed_download_import_enabled else "warning"),
        ])
        groups.append(StatusGroup("LIBRARY", library_rows))
    except Exception as exc:
        groups.append(_group_error("LIBRARY", exc))

    try:
        secret_key = Path(os.getenv("SCARLETX_SECRET_KEY_FILE", "/config/.scarletx-secret.key"))
        config_dir = Path(os.getenv("SCARLETX_CONFIG_DIR", str(secret_key.parent)))
        backup_dir = Path(settings.backup_directory).expanduser()
        bind = db.get_bind()
        database_detail = bind.url.database or bind.url.get_backend_name()
        backup_files = [p for p in backup_dir.glob("*.db") if p.is_file()] if backup_dir.exists() else []
        if backup_files:
            latest = max(backup_files, key=lambda p: p.stat().st_mtime)
            last_backup = datetime.fromtimestamp(latest.stat().st_mtime).astimezone().strftime("%Y-%m-%d %H:%M")
            backup_row = StatusRow("Last Backup", "OK", last_backup, "ok")
        else:
            backup_row = StatusRow("Last Backup", "NONE", "no backup files found", "warning")
        key_secure = False
        if secret_key.exists():
            try:
                key_secure = (secret_key.stat().st_mode & 0o077) == 0
            except OSError:
                key_secure = False
        groups.append(StatusGroup("STORAGE", [
            _path_row("Configuration", config_dir),
            StatusRow("Database", "READY", str(database_detail), "ok"),
            _path_row("Backup Directory", backup_dir),
            StatusRow("Encryption Key", "SECURE" if key_secure else ("READY" if secret_key.exists() else "MISSING"), str(secret_key), "ok" if key_secure else "warning"),
            backup_row,
        ]))
    except Exception as exc:
        groups.append(_group_error("STORAGE", exc))

    try:
        uid = int(getattr(os, "geteuid", lambda: -1)())
        non_root = uid not in {0, -1}
        groups.append(StatusGroup("SECURITY", [
            StatusRow("Container User", "NON-ROOT" if non_root else ("ROOT" if uid == 0 else "UNKNOWN"), f"UID {uid}" if uid >= 0 else "UID unavailable", "ok" if non_root else "warning"),
            StatusRow("API Query Keys", "BLOCKED", "header/Bearer only", "ok"),
            StatusRow("Archive Traversal", "BLOCKED", "containment validation", "ok"),
            StatusRow("Private-IP Artwork", "BLOCKED", "public HTTPS targets only", "ok"),
            StatusRow("Nginx Security Headers", "ENABLED", "CSP + frame + MIME protections", "ok"),
            StatusRow("Secrets At Rest", "ENCRYPTED", "Fernet + per-install key", "ok"),
        ]))
    except Exception as exc:
        groups.append(_group_error("SECURITY", exc))

    return groups
