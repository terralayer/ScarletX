"""Local synthetic same-image burst: no external network or TrueNAS hardware."""
import argparse
import asyncio
from io import BytesIO
import json
from pathlib import Path
import random
import tempfile
import time

from PIL import Image
from scarletx import remote_art


async def main(output):
    source = BytesIO()
    Image.frombytes('RGB', (1600, 900), random.Random(0).randbytes(1600 * 900 * 3)).save(source, 'JPEG', quality=90)
    original = source.getvalue()
    downloads = 0
    resizes = 0
    fit = remote_art.ImageOps.fit
    previous = remote_art.CACHE_ROOT, remote_art._art_client, remote_art._download_public_image

    async def download(*_):
        nonlocal downloads
        downloads += 1
        await asyncio.sleep(.02)
        return original, 'image/jpeg', 'https://example.test/art.jpg'

    def resize(*args, **kwargs):
        nonlocal resizes
        resizes += 1
        return fit(*args, **kwargs)

    lags = []
    finished = False

    async def heartbeat():
        while not finished:
            start = time.perf_counter()
            await asyncio.sleep(.002)
            lags.append(max(0, time.perf_counter() - start - .002) * 1000)

    try:
        with tempfile.TemporaryDirectory() as directory:
            remote_art.CACHE_ROOT = Path(directory)
            remote_art._art_client = lambda: None
            remote_art._download_public_image = download
            remote_art.ImageOps.fit = resize
            monitor = asyncio.create_task(heartbeat())
            start = time.perf_counter()
            results = await asyncio.gather(*(remote_art.cached_remote_thumbnail('burst', ['https://example.test/art.jpg'], (320, 180)) for _ in range(20)))
            elapsed = time.perf_counter() - start
            finished = True
            await monitor
            assert all(result == results[0] for result in results)
        data = {'concurrent_requests': 20, 'simulated_network_delay_ms': 20, 'source_pixels': [1600, 900], 'thumbnail_pixels': [320, 180], 'downloads': downloads, 'resizes': resizes, 'elapsed_ms': round(elapsed * 1000, 2), 'max_event_loop_delay_ms': round(max(lags), 2)}
        output.write_text(json.dumps(data, indent=2))
        print(json.dumps(data, indent=2))
    finally:
        remote_art.CACHE_ROOT, remote_art._art_client, remote_art._download_public_image = previous
        remote_art.ImageOps.fit = fit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
