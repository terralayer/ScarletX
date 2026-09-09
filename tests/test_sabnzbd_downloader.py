from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_active_download_facade_does_not_import_native_usenet():
    source = _source("scarletx/download_clients.py")

    assert "native_usenet" not in source
    assert "enqueue_url" not in source
    assert "native_client_ready" not in source


def test_normal_runtime_does_not_own_native_downloader_supervisor():
    source = _source("scarletx/routes/application.py")

    assert "DownloaderSupervisor" not in source
    assert "downloader_supervisor" not in source


def test_native_downloader_remains_importable_for_compatibility():
    from scarletx import native_usenet
    from scarletx.usenet import worker

    assert native_usenet
    assert worker
