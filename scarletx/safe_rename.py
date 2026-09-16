from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .atomic_publish import publish_file_atomic


class RenamePathError(RuntimeError):
    pass


class RenameCollisionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RenamePlan:
    source: Path
    requested_destination: Path
    destination: Path
    operation: str
    collision: bool


def _validate_destination(path: Path) -> None:
    for component in path.parts:
        if len(component.encode("utf-8")) > 255:
            raise RenamePathError(
                f"Rename path component exceeds 255 bytes: {component[:40]!r}"
            )
    if len(os.fsencode(str(path))) > 4096:
        raise RenamePathError("Rename destination exceeds the supported path length")


def build_rename_plan(source: Path, destination: Path) -> RenamePlan:
    source = Path(source)
    destination = Path(destination)
    if not source.is_file():
        raise RenamePathError(f"Rename source is not a file: {source}")
    _validate_destination(destination)
    if source.resolve() == destination.resolve(strict=False):
        return RenamePlan(
            source=source,
            requested_destination=destination,
            destination=destination,
            operation="noop",
            collision=False,
        )
    return RenamePlan(
        source=source,
        requested_destination=destination,
        destination=destination,
        operation="move",
        collision=destination.exists(),
    )


def execute_rename_plan(plan: RenamePlan) -> Path:
    if plan.operation == "noop":
        return plan.destination
    if plan.collision:
        raise RenameCollisionError(
            "Rename destination already exists; ScarletX will not overwrite it: "
            f"{plan.destination}"
        )
    if plan.operation != "move":
        raise RenamePathError(f"Unsupported rename operation: {plan.operation}")
    return publish_file_atomic(plan.source, plan.destination, mode="move")
