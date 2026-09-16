from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_processing_queue_derives_attempts_elapsed_stage_and_error():
    source = (ROOT / "frontend" / "processing_queue_overrides.js").read_text(encoding="utf-8")

    assert "function attemptCount" in source
    assert "watchdog_retries" in source
    assert "function elapsedSeconds" in source
    assert "started_at" in source
    assert "completed_at" in source
    assert "function stageText" in source
    assert "native.error" in source


def test_processing_queue_renders_required_columns_and_controls():
    source = (ROOT / "frontend" / "processing_queue_overrides.js").read_text(encoding="utf-8")
    base = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    activity = base[base.index("async function activity()") : base.index("async function calendar")]

    for heading in ("Scene", "Stage", "Progress", "Speed", "Attempts", "Elapsed", "Error"):
        assert f"<th>{heading}</th>" in source
    for action in ("pause", "resume", "cancel"):
        assert f'data-native-act="{action}"' in source
    assert "Retry" in activity
    assert "Reprocess" in activity
    assert "Clear Failed" in activity
    assert '<script src="/processing_queue_overrides.js"></script>' in index
