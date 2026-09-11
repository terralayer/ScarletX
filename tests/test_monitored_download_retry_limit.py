from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_monitored_entity_auto_downloads_stop_after_two_retries():
    source = (ROOT / "scarletx" / "automation.py").read_text(encoding="utf-8")

    assert "MAX_MONITORED_AUTO_RETRIES = 2" in source
    assert "failed_attempts >= MAX_MONITORED_AUTO_RETRIES + 1" in source
    assert "TrackedDownload.status == \"failed\"" in source
