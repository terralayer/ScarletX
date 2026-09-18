"""Disposable mixed workload and cache-growth check; no real network or user files.

Use --seconds 28800 for an eight-hour local run. Default: two minutes.
This is not a TrueNAS or Usenet-throughput measurement.
"""

import argparse
from collections import deque
import asyncio
import io
import json
import os
import shutil
import tempfile
import time
from pathlib import Path


def rss_mb():
    try:
        line = next(
            line for line in Path("/proc/self/status").read_text().splitlines() if line.startswith("VmRSS:")
        )
        return round(int(line.split()[1]) / 1024, 2)
    except (OSError, StopIteration):
        return None


async def run(seconds, output):
    with tempfile.TemporaryDirectory(prefix="scarletx-soak-") as temporary:
        root = Path(temporary)
        os.environ["SCARLETX_DATABASE_URL"] = f"sqlite:///{root}/global.db"
        os.environ["SCARLETX_CACHE_DIR"] = str(root / "cache")
        os.environ["SCARLETX_SECRET_KEY_FILE"] = str(root / "secret.key")
        from PIL import Image
        from sqlalchemy import create_engine, insert
        from sqlalchemy.orm import sessionmaker
        from scarletx.db import Base
        from scarletx.models import Scene
        from scarletx.media_library import scan_library
        from scarletx.routes.application import _scene_summary_rows
        from scarletx.wanted import missing_items
        from scarletx import remote_art
        from scarletx.usenet.worker import _run_download_io

        engine = create_engine(f"sqlite:///{root}/library.db", connect_args={"timeout": 20})
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with engine.begin() as conn:
            for start in range(1, 5001, 500):
                conn.execute(
                    insert(Scene),
                    [
                        dict(tpdb_id=str(i), title=f"Fixture {i}", content_type="scene", monitored=True)
                        for i in range(start, start + 500)
                    ],
                )
        media = root / "media"
        media.mkdir()
        for i in range(20):
            (media / f"unmatched-{i}.mp4").write_bytes(b"local fixture" * 100)
        image = io.BytesIO()
        Image.new("RGB", (800, 600), (80, 30, 60)).save(image, format="JPEG")
        payload = image.getvalue()
        downloads = 0

        async def fake_image(*_):
            nonlocal downloads
            downloads += 1
            await asyncio.sleep(0.005)
            return payload, "image/jpeg", "https://example.invalid/fixture"

        original_download = remote_art._download_public_image
        remote_art._download_public_image = fake_image
        source = root / "copy-source.bin"
        source.write_bytes(b"x" * (1024 * 1024))
        counts = dict(reads=0, scans=0, artwork_requests=0, local_file_copies=0)
        latencies, samples = deque(maxlen=10000), deque(maxlen=2048)
        max_lag = 0.0
        rss_first = rss_last = rss_peak = None

        def cache_size():
            files = [p for p in remote_art.CACHE_ROOT.rglob("*") if p.is_file()]
            return dict(files=len(files), bytes=sum(p.stat().st_size for p in files))

        async def artwork_pass():
            for start in range(0, 32, 4):
                await asyncio.gather(
                    *(
                        remote_art.cached_remote_thumbnail(
                            f"soak:{i}", ["https://example.invalid/fixture"], (320, 180)
                        )
                        for i in range(start, start + 4)
                    )
                )
                counts["artwork_requests"] += 4

        await artwork_pass()
        warm_cache = cache_size()
        # Warm scan caches before recording memory growth.
        await asyncio.to_thread(scan_library, factory, directories=[media])
        started = time.monotonic()
        stop_at = started + seconds

        def reads():
            with factory() as db:
                assert len(_scene_summary_rows(db, limit=100)["items"]) == 100
                assert len(missing_items(db, limit=51)) == 51

        async def repeat(operation, interval):
            while time.monotonic() < stop_at:
                await operation()
                await asyncio.sleep(interval)

        async def read_once():
            tick = time.perf_counter()
            await asyncio.to_thread(reads)
            latencies.append((time.perf_counter() - tick) * 1000)
            counts["reads"] += 1

        async def scan_once():
            result = await asyncio.to_thread(scan_library, factory, directories=[media])
            assert not result["errors"]
            counts["scans"] += 1

        async def copy_once():
            await _run_download_io(shutil.copyfile, source, root / "copy-target.bin")
            counts["local_file_copies"] += 1

        async def heartbeat():
            nonlocal max_lag
            while time.monotonic() < stop_at:
                tick = time.perf_counter()
                await asyncio.sleep(0.01)
                max_lag = max(max_lag, max(0, time.perf_counter() - tick - 0.01) * 1000)

        async def sample():
            nonlocal rss_first, rss_last, rss_peak
            current = rss_mb()
            if current is not None:
                rss_first = current if rss_first is None else rss_first
                rss_last = current
                rss_peak = max(rss_peak or current, current)
            samples.append(
                dict(
                    elapsed_s=round(time.monotonic() - started, 1),
                    rss_mb=current,
                    cache=await asyncio.to_thread(cache_size),
                )
            )

        try:
            async with asyncio.TaskGroup() as group:
                for operation, interval in [
                    (read_once, 0.05),
                    (scan_once, 2),
                    (artwork_pass, 0.5),
                    (copy_once, 0.1),
                    (sample, 5),
                ]:
                    group.create_task(repeat(operation, interval))
                group.create_task(heartbeat())
            final_cache = cache_size()
            assert final_cache == warm_cache, "Repeated requests grew the fixed-corpus cache"
            assert downloads == 32, "Cached artwork was downloaded again"
            result = dict(
                duration_seconds=round(time.monotonic() - started, 2),
                workload=counts,
                errors=0,
                read_p95_ms=round(sorted(latencies)[int((len(latencies) - 1) * 0.95)], 2),
                max_event_loop_delay_ms=round(max_lag, 2),
                rss_start_mb=rss_first,
                rss_end_mb=rss_last,
                rss_peak_mb=rss_peak,
                memory_samples=list(samples),
                metric_retention="Latest 10000 read durations and 2048 memory samples; RSS and loop-delay maxima cover full run",
                artwork_downloads=downloads,
                warmed_cache=warm_cache,
                final_cache=final_cache,
                limitations="Synthetic local workload; mocked artwork network, 1 MiB file copies, no Usenet transfer/unpack or TrueNAS hardware. Fixed-corpus cache only; short runs cannot rule out long-term leaks.",
            )
            output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps({k: v for k, v in result.items() if k != "memory_samples"}, indent=2))
        finally:
            remote_art._download_public_image = original_download
            await remote_art.close_remote_art_client()
            engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be at least 1")
    asyncio.run(run(args.seconds, args.output))
