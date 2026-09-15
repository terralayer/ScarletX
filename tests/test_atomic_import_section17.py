from __future__ import annotations

import os

import pytest


def test_same_filesystem_move_publishes_without_partial_file(tmp_path):
    from scarletx.atomic_publish import publish_file_atomic

    source = tmp_path / "processing" / "scene.mkv"
    destination = tmp_path / "library" / "scene.mkv"
    source.parent.mkdir()
    source.write_bytes(b"scene-bytes")

    published = publish_file_atomic(source, destination, mode="move")

    assert published == destination
    assert destination.read_bytes() == b"scene-bytes"
    assert not source.exists()
    assert not list(destination.parent.glob("*.partial-*"))


def test_cross_filesystem_move_copies_to_hidden_temp_then_atomically_publishes(
    tmp_path, monkeypatch
):
    from scarletx import atomic_publish

    source = tmp_path / "processing" / "large.mkv"
    destination = tmp_path / "library" / "large.mkv"
    source.parent.mkdir()
    source.write_bytes(os.urandom(8192))
    monkeypatch.setattr(atomic_publish, "_same_device", lambda *_args: False)

    real_replace = atomic_publish.os.replace
    observed = {}

    def checked_replace(temp, final):
        temp_path = atomic_publish.Path(temp)
        final_path = atomic_publish.Path(final)
        observed["temp"] = temp_path.name
        assert ".partial-" in temp_path.name
        assert not final_path.exists()
        return real_replace(temp, final)

    monkeypatch.setattr(atomic_publish.os, "replace", checked_replace)

    publish_file_atomic = atomic_publish.publish_file_atomic
    publish_file_atomic(source, destination, mode="move")

    assert observed["temp"].startswith(f".{destination.name}.partial-")
    assert destination.stat().st_size == 8192
    assert not source.exists()


def test_failed_cross_filesystem_verification_preserves_source_and_cleans_temp(
    tmp_path, monkeypatch
):
    from scarletx import atomic_publish

    source = tmp_path / "processing" / "broken.mkv"
    destination = tmp_path / "library" / "broken.mkv"
    source.parent.mkdir()
    source.write_bytes(b"important-source")
    monkeypatch.setattr(atomic_publish, "_same_device", lambda *_args: False)

    def reject_copy(_source, _copied):
        raise IOError("verification failed")

    monkeypatch.setattr(atomic_publish, "_verify_copy", reject_copy)

    with pytest.raises(IOError, match="verification failed"):
        atomic_publish.publish_file_atomic(source, destination, mode="move")

    assert source.read_bytes() == b"important-source"
    assert not destination.exists()
    assert not list(destination.parent.glob("*.partial-*"))
