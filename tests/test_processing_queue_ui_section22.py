from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_queue_payload_exposes_attempts_elapsed_and_error():
    source = (ROOT / "scarletx" / "usenet" / "worker.py").read_text(encoding="utf-8")
    start = source.index("def job_dict")
    end = source.index("\n\ndef ", start + 1)
    job_dict = source[start:end]

    assert '"attempts"' in job_dict
    assert '"elapsed_seconds"' in job_dict
    assert '"error": job.error' in job_dict


def test_processing_queue_renders_required_columns_and_controls():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    start = source.index("function activityQueueHtml")
    end = source.index("\n\nfunction applyLiveQueue", start)
    queue = source[start:end]
    activity = source[source.index("async function activity()") : source.index("async function calendar")]

    for heading in ("Scene", "Stage", "Progress", "Speed", "Attempts", "Elapsed", "Error"):
        assert f"<th>{heading}</th>" in queue
    for action in ("pause", "resume", "cancel"):
        assert f'data-native-act="{action}"' in queue
    assert "Retry" in activity
    assert "Reprocess" in activity
    assert "Clear Failed" in activity
