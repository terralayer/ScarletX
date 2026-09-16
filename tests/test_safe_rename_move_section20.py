from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_same_path_builds_noop_plan(tmp_path):
    from scarletx.safe_rename import build_rename_plan

    source = tmp_path / "scene.mkv"
    source.write_bytes(b"video")
    plan = build_rename_plan(source, source)
    assert plan.operation == "noop"
    assert plan.collision is False
    assert plan.destination == source


def test_existing_destination_is_reported_and_never_overwritten(tmp_path):
    from scarletx.safe_rename import RenameCollisionError, build_rename_plan, execute_rename_plan

    source = tmp_path / "source.mkv"
    destination = tmp_path / "destination.mkv"
    source.write_bytes(b"new")
    destination.write_bytes(b"existing")
    plan = build_rename_plan(source, destination)
    assert plan.collision is True
    with pytest.raises(RenameCollisionError):
        execute_rename_plan(plan)
    assert source.read_bytes() == b"new"
    assert destination.read_bytes() == b"existing"


def test_overlong_path_component_is_rejected(tmp_path):
    from scarletx.safe_rename import RenamePathError, build_rename_plan

    source = tmp_path / "source.mkv"
    source.write_bytes(b"video")
    destination = tmp_path / (("x" * 256) + ".mkv")
    with pytest.raises(RenamePathError, match="255"):
        build_rename_plan(source, destination)


def test_execute_move_uses_atomic_publisher(tmp_path, monkeypatch):
    import scarletx.safe_rename as rename

    source = tmp_path / "source.mkv"
    destination = tmp_path / "library" / "scene.mkv"
    source.write_bytes(b"video")
    calls = []

    def fake_publish(src, dst, *, mode):
        calls.append((src, dst, mode))
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return dst

    monkeypatch.setattr(rename, "publish_file_atomic", fake_publish)
    result = rename.execute_rename_plan(rename.build_rename_plan(source, destination))
    assert result == destination
    assert calls == [(source, destination, "move")]


def test_library_rename_surfaces_collision_instead_of_suffixing(tmp_path, monkeypatch):
    import scarletx.library_management as library
    from scarletx.safe_rename import RenameCollisionError

    old = tmp_path / "old.mkv"
    target = tmp_path / "new.mkv"
    old.write_bytes(b"old")
    target.write_bytes(b"existing")
    media = SimpleNamespace(path=str(old), size_bytes=3)
    monkeypatch.setattr(library, "preview_media_rename", lambda *_args, **_kwargs: str(target))

    with pytest.raises(RenameCollisionError):
        library.rename_media_file(SimpleNamespace(flush=lambda: None), media, SimpleNamespace())
    assert media.path == str(old)
    assert old.read_bytes() == b"old"
    assert target.read_bytes() == b"existing"
