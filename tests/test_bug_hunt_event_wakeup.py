from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_completed_import_loop_uses_completion_signal_with_recovery_fallback():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert "awaitcompleted_import_signal.bind()" in compact
    assert "awaitcompleted_import_signal.wait(wait_seconds)" in compact
    assert "COMPLETED_IMPORT_RECOVERY_SECONDS=120" in compact


def test_native_completion_wakes_import_processor():
    source = (ROOT / "scarletx" / "usenet" / "worker.py").read_text(encoding="utf-8")
    assert "completed_import_signal.notify()" in source


def test_native_downloader_uses_signal_with_recovery_fallback():
    source = (ROOT / "scarletx" / "usenet" / "worker.py").read_text(encoding="utf-8")
    compact = "".join(source.split())
    assert "native_queue_signal.notify()" in compact
    assert "awaitnative_queue_signal.bind()" in compact
    assert "awaitnative_queue_signal.wait(NATIVE_QUEUE_RECOVERY_SECONDS)" in compact
    assert "NATIVE_QUEUE_RECOVERY_SECONDS=60" in compact
