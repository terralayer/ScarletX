from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

EXPECTED_MAJOR = 0
EXPECTED_MINOR = 3
EXPECTED_SERIES = "0.3"

VERSIONED_FILES = (
    "pyproject.toml",
    "scarletx/__init__.py",
    "scarletx/routes/application.py",
    "README.md",
    "BUILD-INFO.txt",
    "start-scarletx.sh",
    "Start-ScarletX.ps1",
    "docker-compose.truenas.yml",
    "scarletx/tpdb.py",
    "scarletx/remote_art.py",
    "scarletx/newznab.py",
    "scarletx/usenet/worker.py",
    "packaging/truenas/scarletx/app.yaml",
    "packaging/truenas/scarletx/ix_values.yaml",
)


def parse_version(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"Invalid ScarletX version: {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    if (major, minor) != (EXPECTED_MAJOR, EXPECTED_MINOR):
        raise ValueError(
            f"ScarletX releases must stay in the {EXPECTED_SERIES}.x series; got {version}"
        )
    return major, minor, patch


def parse_release_version(version: str) -> tuple[int, int, int, int | None]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?", version)
    if not match:
        raise ValueError(f"Invalid ScarletX version: {version!r}")
    major, minor, patch = (int(part) for part in match.groups()[:3])
    beta = int(match.group(4)) if match.group(4) is not None else None
    if (major, minor) != (EXPECTED_MAJOR, EXPECTED_MINOR):
        raise ValueError(
            f"ScarletX releases must stay in the {EXPECTED_SERIES}.x series; got {version}"
        )
    if beta is not None and beta < 1:
        raise ValueError(f"Invalid ScarletX beta version: {version!r}")
    return major, minor, patch, beta


def next_patch_version(current: str) -> str:
    major, minor, patch = parse_version(current)
    return f"{major}.{minor}.{patch + 1}"


def next_release_version(current: str) -> str:
    major, minor, patch, beta = parse_release_version(current)
    if beta is not None:
        return f"{major}.{minor}.{patch}"
    return f"{major}.{minor}.{patch + 1}"


def read_project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    parse_release_version(version)
    return version


def replace_version_in_file(path: Path, current: str, next_version: str) -> None:
    text = path.read_text(encoding="utf-8")
    escaped_current = re.escape(current)
    escaped_next = re.escape(next_version)
    updated = text.replace(escaped_current, escaped_next).replace(current, next_version)
    if updated == text:
        raise ValueError(f"No {current} release marker found in {path}")
    path.write_text(updated, encoding="utf-8")


def apply_release(root: Path, notes: str) -> str:
    current = read_project_version(root)
    next_version = next_release_version(current)

    for relative_path in VERSIONED_FILES:
        replace_version_in_file(root / relative_path, current, next_version)

    notes_path = root / f"RELEASE-NOTES-{next_version}.md"
    if notes_path.exists():
        raise ValueError(f"Release notes already exist: {notes_path.name}")
    cleaned_notes = notes.strip()
    if not cleaned_notes:
        raise ValueError("Release notes must not be empty")
    notes_path.write_text(
        f"# ScarletX {next_version}\n\n{cleaned_notes}\n",
        encoding="utf-8",
    )
    return next_version


def main() -> int:
    parser = argparse.ArgumentParser(description="ScarletX patch-only release helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    next_parser = subparsers.add_parser("next", help="Print the next ScarletX stable release version")
    next_parser.add_argument("current")

    apply_parser = subparsers.add_parser("apply", help="Apply the next ScarletX stable release")
    apply_parser.add_argument("--root", type=Path, default=Path.cwd())
    apply_parser.add_argument("--notes", required=True)

    args = parser.parse_args()
    if args.command == "next":
        print(next_release_version(args.current))
        return 0

    next_version = apply_release(args.root.resolve(), args.notes)
    print(next_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
