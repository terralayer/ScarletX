import asyncio
from io import BytesIO
from pathlib import Path
import threading
import time

from PIL import Image
import pytest

from scarletx import remote_art


def image_bytes():
    stream = BytesIO()
    Image.new('RGB', (640, 320), 'red').save(stream, 'PNG')
    return stream.getvalue()


@pytest.mark.asyncio
async def test_burst_shares_download_and_resize_off_event_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_art, 'CACHE_ROOT', tmp_path)
    calls = []
    render_threads = []
    main_thread = threading.get_ident()
    original_fit = remote_art.ImageOps.fit

    async def download(*_):
        calls.append(1)
        await asyncio.sleep(.01)
        return image_bytes(), 'image/png', 'https://example.test/a.png'

    def fit(*args, **kwargs):
        render_threads.append(threading.get_ident())
        time.sleep(.02)
        return original_fit(*args, **kwargs)

    monkeypatch.setattr(remote_art, '_download_public_image', download)
    monkeypatch.setattr(remote_art, '_art_client', lambda: None)
    monkeypatch.setattr(remote_art.ImageOps, 'fit', fit)
    results = await asyncio.gather(*(remote_art.cached_remote_thumbnail('same', ['https://example.test/a.png'], (80, 80)) for _ in range(20)))
    assert len(calls) == 1
    assert len(render_threads) == 1
    assert render_threads[0] != main_thread
    assert all(result == results[0] for result in results)


@pytest.mark.asyncio
async def test_disk_hits_run_off_event_loop_and_contain_is_distinct(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_art, 'CACHE_ROOT', tmp_path)
    remote_art.cache_remote_image_bytes('shape', image_bytes(), 'image/png')
    main_thread = threading.get_ident()
    read_threads = []
    read = Path.read_bytes

    def record(path):
        read_threads.append(threading.get_ident())
        return read(path)

    monkeypatch.setattr(Path, 'read_bytes', record)
    crop, _ = await remote_art.cached_remote_thumbnail('shape', [], (80, 80))
    contain, _ = await remote_art.cached_remote_thumbnail('shape', [], (80, 80), contain=True)
    cached, _ = await remote_art.cached_remote_thumbnail('shape', [], (80, 80), contain=True)
    assert crop != contain
    assert cached == contain
    assert read_threads and main_thread not in read_threads


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_cancel_shared_download(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_art, 'CACHE_ROOT', tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def download(*_):
        calls.append(1)
        entered.set()
        await release.wait()
        return image_bytes(), 'image/png', 'https://example.test/a.png'

    monkeypatch.setattr(remote_art, '_download_public_image', download)
    monkeypatch.setattr(remote_art, '_art_client', lambda: None)
    first = asyncio.create_task(remote_art.cached_remote_image('same', ['url']))
    await entered.wait()
    second = asyncio.create_task(remote_art.cached_remote_image('same', ['url']))
    await asyncio.sleep(.01)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await second)[1] == 'image/png'
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_failed_shared_request_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_art, 'CACHE_ROOT', tmp_path)
    calls = []

    async def download(*_):
        calls.append(1)
        await asyncio.sleep(.01)
        if len(calls) == 1:
            raise remote_art.RemoteArtworkError('temporary failure')
        return image_bytes(), 'image/png', 'url'

    monkeypatch.setattr(remote_art, '_download_public_image', download)
    monkeypatch.setattr(remote_art, '_art_client', lambda: None)
    results = await asyncio.gather(*(remote_art.cached_remote_image('same', ['url']) for _ in range(3)), return_exceptions=True)
    assert all(isinstance(result, remote_art.RemoteArtworkError) for result in results)
    assert (await remote_art.cached_remote_image('same', ['url']))[1] == 'image/png'
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_import_cache_alias_write_runs_off_event_loop(monkeypatch):
    from scarletx import asset_cache
    from scarletx.models import Scene
    from tests.test_auth_routes import make_client
    _, factory = make_client()
    main_thread = threading.get_ident()
    writes = []

    async def cached(*args, **kwargs):
        return b'image', 'image/jpeg'

    monkeypatch.setattr(asset_cache, 'cached_remote_image', cached)
    monkeypatch.setattr(asset_cache, 'cached_remote_thumbnail', cached)
    monkeypatch.setattr(asset_cache, 'cache_remote_image_bytes', lambda *args: writes.append(threading.get_ident()))
    with factory() as db:
        scene = Scene(tpdb_id='alias', title='Alias', content_type='scene', image_url='https://example.test/a.jpg')
        db.add(scene)
        db.commit()
        await asset_cache.cache_scene_asset_bundle(db, scene.id)
    assert writes and main_thread not in writes
