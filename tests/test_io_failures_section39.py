from __future__ import annotations

import errno

import pytest


def test_disk_full_during_atomic_publish_preserves_source_and_cleans_partial(
    tmp_path, monkeypatch
):
    from scarletx import atomic_publish

    source = tmp_path / "processing" / "scene.mkv"
    destination = tmp_path / "library" / "scene.mkv"
    source.parent.mkdir()
    source.write_bytes(b"complete-source")
    monkeypatch.setattr(atomic_publish, "_same_device", lambda *_args: False)

    def fail_copy(_source, temporary):
        atomic_publish.Path(temporary).write_bytes(b"partial")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(atomic_publish.shutil, "copy2", fail_copy)

    with pytest.raises(OSError) as exc_info:
        atomic_publish.publish_file_atomic(source, destination, mode="move")

    assert exc_info.value.errno == errno.ENOSPC
    assert source.read_bytes() == b"complete-source"
    assert not destination.exists()
    assert not list(destination.parent.glob("*.partial-*"))


def test_permission_denied_during_final_publish_preserves_source_and_cleans_partial(
    tmp_path, monkeypatch
):
    from scarletx import atomic_publish

    source = tmp_path / "processing" / "scene.mkv"
    destination = tmp_path / "library" / "scene.mkv"
    source.parent.mkdir()
    source.write_bytes(b"complete-source")
    monkeypatch.setattr(atomic_publish, "_same_device", lambda *_args: False)

    def deny_replace(_temporary, _destination):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(atomic_publish.os, "replace", deny_replace)

    with pytest.raises(PermissionError) as exc_info:
        atomic_publish.publish_file_atomic(source, destination, mode="move")

    assert exc_info.value.errno == errno.EACCES
    assert source.read_bytes() == b"complete-source"
    assert not destination.exists()
    assert not list(destination.parent.glob("*.partial-*"))
