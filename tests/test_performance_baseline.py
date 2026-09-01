import importlib
import json
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCENARIOS = {"list_api", "library_scan", "queue_reads", "tpdb_coalescing"}


def _benchmark_module():
    return importlib.import_module("tools.benchmark_0310")


def run_benchmark_cli(scenario: str, target: Path):
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "benchmark_0310.py"),
            "--scenario",
            scenario,
            "--iterations",
            "1",
            "--json",
            str(target),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_benchmark_result_reports_rate():
    BenchmarkResult = _benchmark_module().BenchmarkResult
    result = BenchmarkResult("scan", 2, 0.5, 10, {})

    assert result.as_dict()["operations_per_second"] == 20.0


def test_cli_writes_machine_readable_result(tmp_path):
    target = tmp_path / "result.json"
    completed = run_benchmark_cli("queue_reads", target)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(target.read_text())
    assert payload["scenario"] == "queue_reads"


def test_harness_exposes_all_planned_scenarios():
    module = _benchmark_module()

    assert set(module.SCENARIOS) == EXPECTED_SCENARIOS


def test_cli_all_writes_every_scenario(tmp_path):
    target = tmp_path / "all.json"
    completed = run_benchmark_cli("all", target)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(target.read_text())
    assert payload["scenario"] == "all"
    assert {item["scenario"] for item in payload["results"]} == EXPECTED_SCENARIOS
