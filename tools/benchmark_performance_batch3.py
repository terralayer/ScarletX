"""Local synthetic comparisons; no external services or user data."""

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import sessionmaker

from scarletx import asset_cache, scan_path_index
from scarletx.db import Base
from scarletx.library_scanner import normalized_path
from scarletx.models import MediaFile, Performer, Scene
from scarletx.usenet.worker import _run_download_io


async def run(output):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        engine = create_engine(f"sqlite:///{root}/bench.db")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        paths = []
        for folder in range(20):
            parent = root / str(folder)
            parent.mkdir()
            paths.extend(str(parent / f"{i}.mp4") for i in range(500))
        with factory() as db:
            scene = Scene(tpdb_id="fixture", title="Fixture")
            scene.performers = [
                Performer(tpdb_id=str(i), name=str(i), image_url="https://example.invalid/image")
                for i in range(16)
            ]
            db.add(scene)
            db.commit()
            scene_id = scene.id
            for offset in range(0, len(paths), 500):
                db.execute(
                    insert(MediaFile), [dict(scene_id=scene_id, path=p) for p in paths[offset : offset + 500]]
                )
            db.commit()
        prefix = str(root / "0") + "/"
        with factory() as db:
            started = time.perf_counter()
            original_ids = [
                row.id
                for row in db.execute(select(MediaFile.id, MediaFile.path))
                if normalized_path(row.path).startswith(prefix)
            ]
            before_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            assert len(list(scan_path_index.scoped_records(db, MediaFile, (prefix,)))) == len(original_ids)
            db.commit()
            backfill_ms = (time.perf_counter() - started) * 1000
            calls = 0
            original_normalize = scan_path_index.normalized_path

            def counted(path):
                nonlocal calls
                calls += 1
                return original_normalize(path)

            scan_path_index.normalized_path = counted
            try:
                started = time.perf_counter()
                actual = [row.id for row in scan_path_index.scoped_records(db, MediaFile, (prefix,))]
                after_ms = (time.perf_counter() - started) * 1000
                assert set(actual) == set(original_ids)
            finally:
                scan_path_index.normalized_path = original_normalize

        async def simulated_image(*args, **kwargs):
            await asyncio.sleep(0.01)
            return b"fixture", "image/jpeg"

        async def serial_map(function, items):
            return [await function(item) for item in items]

        saved = asset_cache.cached_remote_image, asset_cache.cached_remote_thumbnail, asset_cache._bounded_map
        artwork = {}
        try:
            asset_cache.cached_remote_image = simulated_image
            asset_cache.cached_remote_thumbnail = simulated_image
            for name, mapper in [("serial", serial_map), ("bounded_four", saved[2])]:
                asset_cache._bounded_map = mapper
                with factory() as db:
                    started = time.perf_counter()
                    stats = await asset_cache.cache_scene_asset_bundle(db, scene_id)
                    artwork[name + "_ms"] = round((time.perf_counter() - started) * 1000, 2)
                    assert stats["performer_images"] == 16 and not stats["errors"]
        finally:
            asset_cache.cached_remote_image, asset_cache.cached_remote_thumbnail, asset_cache._bounded_map = (
                saved
            )
        loop_delays = {}
        for offload in (False, True):
            delays = []

            async def heartbeat():
                last = time.perf_counter()
                while True:
                    await asyncio.sleep(0.001)
                    now = time.perf_counter()
                    delays.append(max(0, now - last - 0.001) * 1000)
                    last = now

            task = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.005)
            if offload:
                await _run_download_io(time.sleep, 0.05)
            else:
                time.sleep(0.05)
            await asyncio.sleep(0.005)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            loop_delays["offloaded_ms" if offload else "blocking_ms"] = round(max(delays), 2)
        result = dict(
            path_scope=dict(
                files=10000,
                directories=20,
                matched=500,
                before_ms=round(before_ms, 2),
                first_backfill_ms=round(backfill_ms, 2),
                warm_ms=round(after_ms, 2),
                before_resolves=10000,
                warm_resolves=calls,
            ),
            artwork=artwork,
            simulated_50ms_io_event_loop_delay=loop_delays,
            probe_queue=dict(files=10000, previous_submissions=10000, maximum_outstanding_now=4),
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args().output))
