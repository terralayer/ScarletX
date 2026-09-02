from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_phase_metrics_retention_is_bounded():
    from scarletx.download_metrics import DownloadPhaseMetrics

    metrics = DownloadPhaseMetrics(max_jobs=3)
    for index in range(5):
        with metrics.start(f"job-{index}", "receive"):
            pass

    assert metrics.snapshot("job-0") == {}
    assert metrics.snapshot("job-1") == {}
    assert metrics.snapshot("job-2")["receive"]["count"] == 1
    assert metrics.snapshot("job-4")["receive"]["count"] == 1


def test_download_pipeline_benchmark_bounds_buffer_and_keeps_api_responsive(tmp_path):
    target = tmp_path / "download-pipeline.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "benchmark_0310.py"),
            "--scenario",
            "download_pipeline",
            "--iterations",
            "1",
            "--json",
            str(target),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(target.read_text())
    assert payload["scenario"] == "download_pipeline"
    assert payload["operations"] == 10_000
    assert payload["metadata"]["workers"] == 4
    assert payload["metadata"]["max_buffer_size"] == 8
    assert payload["metadata"]["peak_buffer_size"] <= 8
    assert payload["metadata"]["api_rows"] == 200
    assert payload["metadata"]["api_probe_seconds"] < 0.25
    assert set(payload["metadata"]["phase_names"]) == {"decode_write", "receive"}
