from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Iterable, Literal, TextIO

Severity = Literal["ok", "active", "warning", "error"]

_RESET = "\x1b[0m"
_RED = "\x1b[31;1m"
_GREEN = "\x1b[32;1m"
_YELLOW = "\x1b[33;1m"
_CYAN = "\x1b[36;1m"
_DIM = "\x1b[2m"
_GRAY = "\x1b[90m"

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
    return line[:width + 42].rstrip()


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

    if use_color:
        # Scarlet is red; the final X is emphasized bright red by painting the
        # full wordmark red and keeping the rest of the dashboard neutral/cyan.
        wordmark = _paint(_WORDMARK, _RED, True)
    else:
        wordmark = _WORDMARK

    lines = [wordmark, "", "                     TerraLayer Software", f"                       ScarletX {sanitize_console_text(version, limit=30)}", ""]
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
    elif "active" in severities:
        summary = "STATUS:  ✓ ALL SYSTEMS OPERATIONAL"
        summary_color = _GREEN
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
    row = StatusRow(sanitize_console_text(component, limit=34), state_text, sanitize_console_text(detail, limit=120), severity)
    print(_row_line(row, color=use_color, width=72), file=stream, flush=True)
