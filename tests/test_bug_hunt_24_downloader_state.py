from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_hotfix_is_installed_from_composed_app():
    source = (ROOT / "scarletx" / "app.py").read_text(encoding="utf-8")
    assert "install_downloader_state_hotfixes" in source


def test_hotfix_repairs_retry_and_reprocess_state():
    source = (ROOT / "scarletx" / "downloader_state_hotfix.py").read_text(encoding="utf-8")
    assert 'tracked.status = "queued"' in source
    assert 'tracked.client_status = "queued"' in source
    assert "native_queue_signal.notify()" in source
    assert 'tracked.status == "import_failed"' in source
    assert 'tracked.status = "import_pending"' in source


def test_hotfix_serializes_duplicate_native_enqueue():
    source = (ROOT / "scarletx" / "downloader_state_hotfix.py").read_text(encoding="utf-8")
    assert "_ENQUEUE_LOCK" in source
    assert "with _ENQUEUE_LOCK:" in source
    assert "download_clients.enqueue_url = enqueue_url_hotfix" in source


def test_hotfix_keeps_paused_job_paused_before_worker_claim():
    source = (ROOT / "scarletx" / "downloader_state_hotfix.py").read_text(encoding="utf-8")
    assert "async def process_job_hotfix" in source
    assert 'if job.status == "paused":' in source
    assert "worker.process_job = process_job_hotfix" in source
