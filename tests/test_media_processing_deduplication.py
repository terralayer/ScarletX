from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import RootFolder


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def test_matching_import_identity_is_suppressed(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    registry = RecentImportRegistry()
    identity = FileIdentity.from_path(video)
    registry.register(identity)
    assert registry.contains(FileIdentity.from_path(video)) is True


def test_modified_import_is_processed(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    registry = RecentImportRegistry()
    registry.register(FileIdentity.from_path(video))
    video.write_bytes(b"changed content")
    assert registry.contains(FileIdentity.from_path(video)) is False


def test_same_size_nanosecond_change_is_processed(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    registry = RecentImportRegistry()
    original = FileIdentity.from_path(video)
    registry.register(original)
    video.touch()
    changed = FileIdentity.from_path(video)
    if changed.mtime_ns == original.mtime_ns:
        pytest.skip("filesystem did not expose a new nanosecond mtime")
    assert registry.contains(changed) is False


def test_registry_expires_entries_at_ttl(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    clock = Clock()
    video = tmp_path / "scene.mp4"
    video.touch()
    identity = FileIdentity.from_path(video)
    registry = RecentImportRegistry(ttl_seconds=5, clock=clock)
    registry.register(identity)
    clock.value = 5.0
    assert registry.contains(identity) is False


def test_lru_touch_does_not_extend_ttl(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    clock = Clock()
    first = tmp_path / "first.mp4"
    second = tmp_path / "second.mp4"
    first.touch()
    second.touch()
    identities = [FileIdentity.from_path(first), FileIdentity.from_path(second)]
    registry = RecentImportRegistry(ttl_seconds=5, clock=clock)
    registry.register(identities[0])
    clock.value = 1.0
    registry.register(identities[1])
    clock.value = 4.0
    assert registry.contains(identities[0]) is True
    clock.value = 5.0
    assert registry.contains(identities[0]) is False
    assert registry.contains(identities[1]) is True


def test_registry_is_lru_bounded(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    paths = [tmp_path / f"{index}.mp4" for index in range(3)]
    for path in paths:
        path.touch()
    identities = [FileIdentity.from_path(path) for path in paths]
    registry = RecentImportRegistry(max_entries=2)
    registry.register(identities[0])
    registry.register(identities[1])
    assert registry.contains(identities[0]) is True
    registry.register(identities[2])
    assert registry.contains(identities[0]) is True
    assert registry.contains(identities[1]) is False


def test_new_registry_after_restart_causes_harmless_recheck(tmp_path):
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    video = tmp_path / "scene.mp4"
    video.touch()
    identity = FileIdentity.from_path(video)
    before_restart = RecentImportRegistry()
    before_restart.register(identity)
    after_restart = RecentImportRegistry()
    assert after_restart.contains(identity) is False


def test_scanner_unchanged_check_suppresses_registered_import(tmp_path, monkeypatch):
    from scarletx import library_scanner
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    registry = RecentImportRegistry()
    registry.register(FileIdentity.from_path(video))
    monkeypatch.setattr(library_scanner, "recent_imports", registry)
    assert library_scanner.unchanged(None, video.stat(), path=video) is True


def test_registered_import_skips_scanner_fingerprint_and_modified_file_bypasses(tmp_path, monkeypatch):
    from scarletx import library_scanner, media_library
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    root = tmp_path / "library"
    root.mkdir()
    video = root / "scene.mp4"
    video.write_bytes(b"video")
    engine = create_engine(f"sqlite:///{tmp_path / 'dedupe.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(RootFolder(name="Scenes", content_type="scene", path=str(root), is_default=True))
        db.commit()

    registry = RecentImportRegistry()
    registry.register(FileIdentity.from_path(video))
    monkeypatch.setattr(library_scanner, "recent_imports", registry)
    calls = 0

    def fingerprint(_path):
        nonlocal calls
        calls += 1
        return "f" * 64

    monkeypatch.setattr(media_library, "quick_fingerprint", fingerprint)
    assert media_library.scan_library(factory)["skipped"] == 1
    assert calls == 0

    video.write_bytes(b"changed")
    assert media_library.scan_library(factory)["unmatched"] == 1
    assert calls == 1
    engine.dispose()


def test_watcher_suppresses_only_exact_changed_identity(tmp_path, monkeypatch):
    from scarletx import media_watch
    from scarletx.recent_imports import FileIdentity, RecentImportRegistry

    video = tmp_path / "scene.mp4"
    video.write_bytes(b"video")
    registry = RecentImportRegistry()
    registry.register(FileIdentity.from_path(video))
    monkeypatch.setattr(media_watch, "recent_imports", registry)
    assert media_watch._suppress_recent_import("changed", video) is True
    assert media_watch._suppress_recent_import("deleted", video) is False
    video.write_bytes(b"changed")
    assert media_watch._suppress_recent_import("changed", video) is False


def test_failed_import_is_not_registered_before_commit():
    source = Path("scarletx/download_processing.py").read_text()
    commit = source.index("db.commit()", source.index("import_media_file("))
    registration = source.index("recent_imports.register", source.index("import_media_file("))
    assert commit < registration
