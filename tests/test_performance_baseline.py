import importlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCENARIOS = {"idle_ui", "list_api", "library_scan", "queue_reads", "tpdb_coalescing"}


def _benchmark_module():
    return importlib.import_module("tools.benchmark_0310")


def run_benchmark_cli(scenario: str, target: Path, iterations: int = 1):
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "benchmark_0310.py"),
            "--scenario",
            scenario,
            "--iterations",
            str(iterations),
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
    assert payload["iterations"] == 1
    results = {item["scenario"]: item for item in payload["results"]}
    assert set(results) == EXPECTED_SCENARIOS


assert results["idle_ui"]["operations"] == 10_000
assert results["idle_ui"]["metadata"]["modeled_session_seconds"] == 600
assert results["idle_ui"]["metadata"]["healthy_sse_queue_requests"] == 0
assert results["idle_ui"]["metadata"]["subscriber_queue_size"] == 64
assert results["idle_ui"]["metadata"]["replay_size"] == 512
assert len(results["idle_ui"]["metadata"]["samples_seconds"]) == 1

    assert results["list_api"]["operations"] == 100
    assert results["list_api"]["metadata"]["fixture_scenes"] == 1_000
    assert results["list_api"]["metadata"]["page_size"] == 100
    assert len(results["list_api"]["metadata"]["samples_seconds"]) == 1

    assert results["library_scan"]["operations"] == 10_000
    assert results["library_scan"]["metadata"]["fixture_files"] == 10_000
    assert results["library_scan"]["metadata"]["fixture_directories"] == 100
    assert results["library_scan"]["metadata"]["warmup"]["files"] == 10_000
    assert results["library_scan"]["metadata"]["last_scan"]["files"] == 10_000
    assert len(results["library_scan"]["metadata"]["samples_seconds"]) == 1

    assert results["queue_reads"]["operations"] == 200
    assert results["queue_reads"]["metadata"]["fixture_jobs"] == 200
    assert len(results["queue_reads"]["metadata"]["samples_seconds"]) == 1

    assert results["tpdb_coalescing"]["operations"] == 100
    assert results["tpdb_coalescing"]["metadata"]["concurrent_reads"] == 100
    assert results["tpdb_coalescing"]["metadata"]["network_calls"] == [1]
    assert len(results["tpdb_coalescing"]["metadata"]["samples_seconds"]) == 1


def test_tpdb_benchmark_isolates_each_cold_coalescing_sample(tmp_path):
    target = tmp_path / "tpdb.json"
    completed = run_benchmark_cli("tpdb_coalescing", target, iterations=5)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(target.read_text())
    assert payload["iterations"] == 5
    assert payload["metadata"]["network_calls"] == [1, 1, 1, 1, 1]
    assert len(payload["metadata"]["samples_seconds"]) == 5


def test_queue_benchmark_reports_durable_progress_write_budget(tmp_path):
    target = tmp_path / "queue.json"
    completed = run_benchmark_cli("queue_reads", target, iterations=1)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(target.read_text())
    checkpoint = payload["metadata"]["progress_checkpoint"]
    assert checkpoint["updates"] == 1_000
    assert checkpoint["duration_seconds"] == 10.0
    assert checkpoint["bytes_per_update"] == 4 * 1024
    assert checkpoint["checkpoint_writes"] == 5


def _run_ruff(*targets: Path | str):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(REPO_ROOT / "pyproject.toml"),
            *(str(target) for target in targets),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ruff_baseline_accepts_existing_source_tree():
    completed = _run_ruff("scarletx", "tests", "tools")

    assert completed.returncode == 0, completed.stdout


def test_ruff_baseline_rejects_undefined_names(tmp_path):
    target = tmp_path / "undefined_name.py"
    target.write_text("result = missing_value\n")

    completed = _run_ruff(target)

    assert completed.returncode == 1
    assert "F821" in completed.stdout


def test_ruff_baseline_rejects_unused_imports_in_new_files(tmp_path):
    target = tmp_path / "unused_import.py"
    target.write_text("import os\n")

    completed = _run_ruff(target)

    assert completed.returncode == 1
    assert "F401" in completed.stdout


def test_ruff_baseline_rejects_multiple_statements_in_new_files(tmp_path):
    target = tmp_path / "multiple_statements.py"
    target.write_text("value = 1; result = value + 1\n")

    completed = _run_ruff(target)

    assert completed.returncode == 1
    assert "E702" in completed.stdout
