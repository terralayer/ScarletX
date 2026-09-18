import asyncio
import concurrent.futures
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import event

from scarletx.models import Scene, Performer, MediaFile
from tests.test_incremental_scanner import _database


def test_probe_submissions_are_bounded():
    from scarletx.media_library import _bounded_probe_futures

    class Pool:
        outstanding = 0
        peak = 0

        def submit(self, function, *args, **kwargs):
            self.outstanding += 1
            self.peak = max(self.peak, self.outstanding)
            future = concurrent.futures.Future()
            future.set_result(True)
            return future

    pool = Pool()
    seen = []
    for media_id, future in _bounded_probe_futures(pool, None, range(10000), 2):
        seen.append(media_id)
        assert future.result()
        pool.outstanding -= 1
    assert len(seen) == 10000
    assert pool.peak <= 4


def test_scene_list_omits_heavy_columns(tmp_path):
    from scarletx.routes.application import _scene_summary_rows

    engine, factory = _database(tmp_path)
    with factory() as db:
        db.add(Scene(tpdb_id="slim", title="Slim", description="x" * 100000))
        db.commit()
    statements = []
    event.listen(
        engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement)
    )
    with factory() as db:
        assert _scene_summary_rows(db, limit=10)["items"][0]["title"] == "Slim"
    assert not any("scenes.description" in sql for sql in statements)
    engine.dispose()


@pytest.mark.asyncio
async def test_artwork_warmer_is_concurrent_and_bounded(tmp_path, monkeypatch):
    from scarletx import asset_cache

    engine, factory = _database(tmp_path)
    with factory() as db:
        scene = Scene(tpdb_id="warm", title="Warm")
        scene.performers = [
            Performer(tpdb_id=str(i), name=str(i), image_url="https://example.invalid/image")
            for i in range(15)
        ]
        db.add(scene)
        db.commit()
        scene_id = scene.id
    active = peak = 0

    async def cached(*args, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.005)
        active -= 1
        return b"image", "image/jpeg"

    monkeypatch.setattr(asset_cache, "cached_remote_image", cached)
    monkeypatch.setattr(asset_cache, "cached_remote_thumbnail", cached)
    with factory() as db:
        result = await asset_cache.cache_scene_asset_bundle(db, scene_id)
    assert result["performer_images"] == 15
    assert result["errors"] == 0
    assert 1 < peak <= 4
    engine.dispose()


def test_cached_scope_avoids_resolving_every_file(tmp_path, monkeypatch):
    from scarletx import scan_path_index

    engine, factory = _database(tmp_path)
    root = tmp_path / "library"
    root.mkdir()
    with factory() as db:
        scene = Scene(tpdb_id="paths", title="Paths")
        db.add(scene)
        db.flush()
        db.add_all(MediaFile(scene_id=scene.id, path=str(root / f"{i}.mp4")) for i in range(2000))
        db.commit()
    prefix = str(root) + "/"
    with factory() as db:
        assert len(list(scan_path_index.scoped_records(db, MediaFile, (prefix,)))) == 2000
        db.commit()
    calls = Counter()
    original = scan_path_index.normalized_path

    def counted(path):
        calls["resolve"] += 1
        return original(path)

    monkeypatch.setattr(scan_path_index, "normalized_path", counted)
    with factory() as db:
        assert len(list(scan_path_index.scoped_records(db, MediaFile, (prefix,)))) == 2000
    assert calls["resolve"] < 10
    engine.dispose()


def test_index_refreshes_retargeted_symlink_and_db_paths(tmp_path):
    from scarletx.scan_path_index import scoped_records

    engine, factory = _database(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(first, target_is_directory=True)
    with factory() as db:
        scene = Scene(tpdb_id="alias", title="Alias")
        db.add(scene)
        db.flush()
        media = MediaFile(scene_id=scene.id, path=str(alias / "video.mp4"))
        db.add(media)
        db.commit()
        assert len(list(scoped_records(db, MediaFile, (str(first) + "/",)))) == 1
        db.commit()
        alias.unlink()
        alias.symlink_to(second, target_is_directory=True)
        assert list(scoped_records(db, MediaFile, (str(first) + "/",))) == []
        assert len(list(scoped_records(db, MediaFile, (str(second) + "/",)))) == 1
        media.path = str(first / "changed.mp4")
        db.commit()
        assert len(list(scoped_records(db, MediaFile, (str(first) + "/",)))) == 1
        db.delete(media)
        db.commit()
        assert list(scoped_records(db, MediaFile, (str(first) + "/",))) == []
    engine.dispose()


@pytest.mark.asyncio
async def test_download_io_runs_off_loop_and_drains_before_cancellation():
    import threading
    from scarletx.usenet.worker import _run_download_io

    main_thread = threading.get_ident()
    started, release = threading.Event(), threading.Event()
    threads = []

    def slow_write():
        threads.append(threading.get_ident())
        started.set()
        release.wait(timeout=2)
        return "written"

    task = asyncio.create_task(_run_download_io(slow_write))
    while not started.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done(), "Shutdown must wait for in-flight filesystem writes"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert threads and main_thread not in threads


def test_path_index_refreshes_replaced_file_symlinks(tmp_path):
    from scarletx.scan_path_index import scoped_records

    engine, factory = _database(tmp_path)
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    file = source / "video.mp4"
    file.write_bytes(b"first")
    with factory() as db:
        scene = Scene(tpdb_id="replacement", title="Replacement")
        db.add(scene)
        db.flush()
        db.add(MediaFile(scene_id=scene.id, path=str(file)))
        db.commit()
        assert len(list(scoped_records(db, MediaFile, (str(source) + "/",)))) == 1
        db.commit()
        file.unlink()
        file.symlink_to(target / "target.mp4")
        assert list(scoped_records(db, MediaFile, (str(source) + "/",))) == []
        assert len(list(scoped_records(db, MediaFile, (str(target) + "/",)))) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_artwork_cancellation_drains_other_workers():
    from scarletx.asset_cache import _bounded_map

    entered = asyncio.Event()
    active = 0

    async def wait(_):
        nonlocal active
        active += 1
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            active -= 1

    task = asyncio.create_task(_bounded_map(wait, list(range(20))))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at_completion", [False, True])
async def test_resumed_download_finishes_without_losing_final_path(
    tmp_path, monkeypatch, cancel_at_completion
):
    import threading
    from types import SimpleNamespace
    from scarletx.usenet import worker
    from scarletx.models import NativeUsenetJob

    engine, factory = _database(tmp_path)
    work = tmp_path / "incomplete" / "finish"
    assembly = work / "assembly"
    state = work / "segments" / "0001"
    assembly.mkdir(parents=True)
    state.mkdir(parents=True)
    (work / "source.nzb").write_bytes(b"fixture")
    (assembly / "0001.part").write_bytes(b"video")
    (state / "filename.txt").write_text("scene.mp4")
    worker._write_done_marker(state / "000001.done", 5, 1, None)
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id="finish", title="Finish", nzb_url="https://example.invalid/nzb", status="queued"
            )
        )
        db.commit()
    monkeypatch.setattr(
        worker,
        "parse_nzb",
        lambda _: [worker.NZBFile("scene.mp4", (), (worker.NZBSegment(1, 5, "fixture"),))],
    )
    monkeypatch.setattr(worker, "validate_nzb_release_size", lambda _: None)
    fetcher = SimpleNamespace(
        close_target=lambda *a: None,
        close_targets_under=lambda *a: None,
        best_provider=lambda: None,
        provider_stats=lambda: [],
        abort_active=lambda: None,
    )
    monkeypatch.setattr(worker, "_shared_segment_fetcher", lambda *a: fetcher)
    monkeypatch.setattr(
        worker, "postprocess_payload", lambda payload, **kwargs: ([], [payload / "scene.mp4"])
    )
    settings = SimpleNamespace(
        native_usenet_incomplete_dir=str(tmp_path / "incomplete"),
        native_usenet_complete_dir=str(tmp_path / "complete"),
        native_usenet_providers=lambda: [
            SimpleNamespace(enabled=True, host="example.invalid", connections=1)
        ],
        native_usenet_max_connections=1,
        native_usenet_max_retries=0,
        native_usenet_unpack_enabled=False,
        native_usenet_repair_enabled=False,
    )
    entered, release = threading.Event(), threading.Event()
    original = worker._set_job
    main_thread = threading.get_ident()
    completion_threads = []

    def set_job(*args, **kwargs):
        original(*args, **kwargs)
        if kwargs.get("status") == "completed":
            completion_threads.append(threading.get_ident())
            entered.set()
            if cancel_at_completion:
                release.wait(timeout=3)

    monkeypatch.setattr(worker, "_set_job", set_job)
    task = asyncio.create_task(worker.process_job(factory, settings, "finish"))
    if cancel_at_completion:

        async def wait_entered():
            while not entered.is_set():
                await asyncio.sleep(0.001)

        await asyncio.wait_for(wait_entered(), timeout=2)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await asyncio.wait_for(task, timeout=2)
    with factory() as db:
        job = db.get(NativeUsenetJob, "finish")
        assert job.status == "completed"
        assert (Path(job.output_path) / "scene.mp4").read_bytes() == b"video"
        assert not work.exists()
    assert completion_threads and main_thread not in completion_threads
    engine.dispose()
