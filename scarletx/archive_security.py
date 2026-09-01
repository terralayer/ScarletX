from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

_DRIVE = re.compile(r"^[A-Za-z]:")


def validate_archive_member_path(name: str) -> PurePosixPath:
    raw = str(name or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or _DRIVE.match(raw):
        raise ValueError("archive member path is absolute or empty")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("archive member path contains traversal components")
    return path


def parse_7z_listing(output: str) -> list[str]:
    members: list[str] = []
    in_entries = False
    for line in (output or "").splitlines():
        if line.strip().startswith("----------"):
            in_entries = True
            continue
        if in_entries and line.startswith("Path = "):
            name = line[7:].strip()
            validate_archive_member_path(name)
            members.append(name)
    return members


def validate_extracted_tree(root: Path) -> None:
    base = root.resolve()
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"archive extracted a symbolic link: {item.name}")
        resolved = item.resolve(strict=False)
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"archive extraction escaped quarantine: {item}") from exc
