from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.library_scanner import DirtyDirectoryQueue, scan_directories
from scarletx.media_library import scan_library
from scarletx.models import FileScanState, MediaFile, MediaProbe, RootFolder, Scene
from tools.benchmark_0310 import run_scenario


def _database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scanner.sqlite3'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _add_root(factory, root: Path) -> None:
    with factory() as db:
        db.add(RootFolder(name="Scenes", content_type="scene", path=str(root), is_default=True))
        db.commit()


def test_repeated_events_coalesce_to_one_directory(tmp_path):
    queue = DirtyDirectoryQueue()
    queue.mark(tmp_path / "a.mp4")
    queue.mark(tmp_path / "b.mp4")
    assert queue.drain(10) == [tmp_path.resolve()]


def test_queue_overflow_is_reported_once(tmp_path):
    queue = DirtyDirectoryQueue(max_entries=1)
    queue.mark(tmp_path / "a" / "one.mp4")
    queue.mark(tmp_path / "b" / "two.mp4")
    assert queue.overflow() is True
    assert queue.overflow() is False


def test_unchanged_file_is_not_fingerprinted_twice(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    video = root / "unmatched.mp4"
    video.write_bytes(b"video")
    engine, factory = _database(tmp_path)
    _add_root(factory, root)
    calls = 0

    def fingerprint(_path):
        nonlocal calls
        calls += 1
        return "f" * 64

    monkeypatch.setattr("scarletx.media_library.quick_fingerprint", fingerprint)
    assert scan_library(factory)["unmatched"] == 1
    assert scan_library(factory)["skipped"] == 1
    assert calls == 1
    engine.dispose()


def test_scan_state_survives_new_session_factory(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    (root / "unmatched.mp4").write_bytes(b"video")
    engine, factory = _database(tmp_path)
    _add_root(factory, root)
    monkeypatch.setattr("scarletx.media_library.quick_fingerprint", lambda _path: "f" * 64)
    scan_library(factory)
    restarted_factory = sessionmaker(bind=engine, expire_on_commit=False)
    assert scan_library(restarted_factory)["skipped"] == 1
    engine.dispose()


def test_nanosecond_mtime_change_is_not_skipped(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    video = root / "unmatched.mp4"
    video.write_bytes(b"video")
    engine, factory = _database(tmp_path)
    _add_root(factory, root)
    calls = 0

    def fingerprint(_path):
        nonlocal calls
        calls += 1
        return str(calls) * 64

    monkeypatch.setattr("scarletx.media_library.quick_fingerprint", fingerprint)
    scan_library(factory)
    before = video.stat()
    os.utime(video, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
    assert scan_library(factory)["unmatched"] == 1
    assert calls == 2
    engine.dispose()


def test_missing_state_reconciliation_is_scoped(tmp_path, monkeypatch):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    video_a = root_a / "a.mp4"
    video_b = root_b / "b.mp4"
    video_a.write_bytes(b"a")
    video_b.write_bytes(b"b")
    engine, factory = _database(tmp_path)
    _add_root(factory, root_a)
    monkeypatch.setattr("scarletx.media_library.quick_fingerprint", lambda _path: "f" * 64)
    scan_library(factory)
    with factory() as db:
        stat_b = video_b.stat()
        db.add(FileScanState(path=str(video_b.resolve()), size_bytes=stat_b.st_size, mtime_ns=stat_b.st_mtime_ns))
        db.commit()
    video_a.unlink()
    scan_library(factory)
    with factory() as db:
        paths = set(db.scalars(select(FileScanState.path)).all())
    assert str(video_a.resolve()) not in paths
    assert str(video_b.resolve()) in paths
    engine.dispose()


def test_unreadable_directory_stays_in_state_for_retry(tmp_path, monkeypatch):
    root = tmp_path / "library"
    root.mkdir()
    video = root / "unmatched.mp4"
    video.write_bytes(b"video")
    engine, factory = _database(tmp_path)
    _add_root(factory, root)
    monkeypatch.setattr("scarletx.media_library.quick_fingerprint", lambda _path: "f" * 64)
    scan_library(factory)

    real_scandir = os.scandir

    def denied(path):
        if Path(path) == root:
            raise PermissionError("test denial")
        return real_scandir(path)

    monkeypatch.setattr("scarletx.library_scanner.os.scandir", denied)
    result = scan_directories(factory, [root])
    assert result["failed_directories"] == [str(root)]
    with factory() as db:
        assert db.get(FileScanState, str(video.resolve())) is not None
    engine.dispose()


def test_benchmark_reports_zero_unchanged_expensive_probes(tmp_path):
    result = run_scenario("library_scan", 1, tmp_path)
    assert result.metadata["unchanged_expensive_probes"] == 0


def test_dirty_scope_does_not_reconcile_deleted_file_elsewhere(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    engine, factory = _database(tmp_path)
    with factory() as db:
        scene = Scene(tpdb_id="scope", title="Scoped Scene", content_type="scene")
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path=str(root_b / "gone.mp4"))
        db.add(media)
        db.flush()
        db.add(MediaProbe(media_file_id=media.id, missing=False))
        db.commit()
        media_id = media.id

    scan_directories(factory, [root_a])

    with factory() as db:
        assert db.get(MediaProbe, media_id).missing is False
    engine.dispose()
