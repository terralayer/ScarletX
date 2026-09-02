from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


native_path = Path("scarletx/native_usenet.py")
native = native_path.read_text()
native = replace_once(
    native,
    "from .progress import ProgressCheckpointGate\n",
    "from .progress import ProgressCheckpointGate\nfrom .download_metrics import SegmentResultBuffer, download_phase_metrics\n",
    "native metrics import",
)
native = replace_once(
    native,
    "    def fetch_into(self, segment: NZBSegment, target: Path, done_marker: Path) -> DecodedSegment:\n",
    "    def fetch_into(\n        self, segment: NZBSegment, target: Path, done_marker: Path, *, job_id: str | None = None\n    ) -> DecodedSegment:\n",
    "fetch_into signature",
)
native = replace_once(
    native,
    "                        size, filename, begin, total_size = decode_yenc_native(\n                            connection, segment, self._target_writer(target)\n                        )\n",
    "                        with download_phase_metrics.start(job_id, \"receive\"):\n                            with download_phase_metrics.start(job_id, \"decode_write\"):\n                                size, filename, begin, total_size = decode_yenc_native(\n                                    connection, segment, self._target_writer(target)\n                                )\n",
    "native decoder timing",
)
native = replace_once(
    native,
    "                    size, filename, begin, total_size = decode_yenc_to_target(\n                        connection.body_iter(segment.message_id), target,\n                        write_lock=self._target_lock(target),\n                    )\n",
    "                    with download_phase_metrics.start(job_id, \"receive\"):\n                        with download_phase_metrics.start(job_id, \"decode_write\"):\n                            size, filename, begin, total_size = decode_yenc_to_target(\n                                connection.body_iter(segment.message_id), target,\n                                write_lock=self._target_lock(target),\n                            )\n",
    "fallback decoder timing",
)
native = replace_once(
    native,
    "    verified = _run_tool(verify_cmd, payload_dir, 180, job_id=job_id, label=\"PAR2 verification\")\n",
    "    with download_phase_metrics.start(job_id, \"verify\"):\n        verified = _run_tool(verify_cmd, payload_dir, 180, job_id=job_id, label=\"PAR2 verification\")\n",
    "verify phase",
)
native = replace_once(
    native,
    "    repaired = _run_tool(repair_cmd, payload_dir, 600, job_id=job_id, label=\"PAR2 repair\")\n",
    "    with download_phase_metrics.start(job_id, \"repair\"):\n        repaired = _run_tool(repair_cmd, payload_dir, 600, job_id=job_id, label=\"PAR2 repair\")\n",
    "repair phase",
)
native, probe_count = re.subn(
    r'(?m)^(\s*)notes\.extend\(recover_unknown_videos\(payload_dir\)\)$',
    lambda m: (
        f'{m.group(1)}with download_phase_metrics.start(job_id, "probe"):\n'
        f'{m.group(1)}    notes.extend(recover_unknown_videos(payload_dir))'
    ),
    native,
)
if probe_count < 2:
    raise SystemExit(f"probe phases: expected at least 2 matches, found {probe_count}")
native = replace_once(
    native,
    "        notes.extend(unpack_payload(payload_dir, unpack_enabled, password, job_id=job_id))\n",
    "        with download_phase_metrics.start(job_id, \"extract\"):\n            notes.extend(unpack_payload(payload_dir, unpack_enabled, password, job_id=job_id))\n",
    "extract phase",
)

old_setup = '''            loop = asyncio.get_running_loop()
            position = 0
            inflight: dict[asyncio.Future, tuple[int, Path]] = {}
            tune_time = time.monotonic()
            tune_speed = 0.0
            stable_rounds = 0

            def submit_until_window() -> None:
                nonlocal position
                while len(inflight) < active_window and position < len(jobs):
                    _, idx, _, segment, target, done_marker, filename_marker = jobs[position]
                    position += 1
                    future = loop.run_in_executor(executor, fetcher.fetch_into, segment, target, done_marker)
                    inflight[future] = (idx, filename_marker)
'''
new_setup = '''            loop = asyncio.get_running_loop()
            position = 0
            result_buffer = SegmentResultBuffer(hard_cap)
            inflight: dict[int, tuple[asyncio.Future, int, Path]] = {}
            tune_time = time.monotonic()
            tune_speed = 0.0
            stable_rounds = 0

            def fetch_and_buffer(
                token: int, segment: NZBSegment, target: Path, done_marker: Path
            ) -> None:
                try:
                    result = fetcher.fetch_into(
                        segment, target, done_marker, job_id=job_id
                    )
                except BaseException as exc:
                    result_buffer.put((token, None, exc))
                else:
                    result_buffer.put((token, result, None))

            def submit_until_window() -> None:
                nonlocal position
                while len(inflight) < active_window and position < len(jobs):
                    _, idx, _, segment, target, done_marker, filename_marker = jobs[position]
                    token = position
                    position += 1
                    future = loop.run_in_executor(
                        executor, fetch_and_buffer, token, segment, target, done_marker
                    )
                    inflight[token] = (future, idx, filename_marker)
'''
native = replace_once(native, old_setup, new_setup, "bounded result setup")

old_wait = '''                done, _ = await asyncio.wait(set(inflight), timeout=0.20, return_when=asyncio.FIRST_COMPLETED)
                if done:
                    for future in done:
                        idx, filename_marker = inflight.pop(future)
                        result = future.result()
                        downloaded += result.size
                        session_downloaded += result.size
                        if result.filename and not filename_marker.exists():
                            try:
                                temp = filename_marker.with_name("filename.txt.tmp")
                                temp.write_text(_safe_filename(result.filename, f"file-{idx:04d}.bin"))
                                temp.replace(filename_marker)
                            except Exception:
                                pass

'''
new_wait = '''                try:
                    token, result, error = result_buffer.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.02)
                else:
                    future, idx, filename_marker = inflight.pop(token)
                    await future
                    if error is not None:
                        raise error
                    downloaded += result.size
                    session_downloaded += result.size
                    if result.filename and not filename_marker.exists():
                        try:
                            temp = filename_marker.with_name("filename.txt.tmp")
                            temp.write_text(_safe_filename(result.filename, f"file-{idx:04d}.bin"))
                            temp.replace(filename_marker)
                        except Exception:
                            pass

'''
native = replace_once(native, old_wait, new_wait, "bounded result drain")
native = replace_once(
    native,
    "                    phase=\"recovery\" if recovery else \"payload\",\n",
    "                    phase=\"recovery\" if recovery else \"payload\",\n                    buffered_segments=result_buffer.qsize(),\n                    max_buffered_segments=result_buffer.peak_size,\n",
    "live buffer telemetry",
)
old_cancel = '''    except asyncio.CancelledError:
        shutil.rmtree(work, ignore_errors=True)
        _set_job(session_factory, job_id, status="cancelled", speed_bps=0.0, eta_seconds=0, output_path=None, error=None, completed_at=utcnow(), unpack_password=None)
'''
new_cancel = '''    except asyncio.CancelledError:
        _set_job(
            session_factory, job_id, status="cancelled", speed_bps=0.0, eta_seconds=0,
            output_path=str(work) if work.exists() else None, error=None,
            postprocess_note="Cancelled; partial data preserved for retry",
            completed_at=utcnow(), unpack_password=None,
        )
'''
native = replace_once(native, old_cancel, new_cancel, "cancel preservation")
native = replace_once(
    native,
    '        "phase": live.get("phase"),\n',
    '        "phase": live.get("phase"),\n        "buffered_segments": live.get("buffered_segments", 0),\n        "max_buffered_segments": live.get("max_buffered_segments", 0),\n        "phase_metrics": download_phase_metrics.snapshot(job.id),\n',
    "job metrics output",
)
native_path.write_text(native)

import_path = Path("scarletx/download_processing.py")
imports = import_path.read_text()
imports = replace_once(
    imports,
    "from .config import Settings\n",
    "from .config import Settings\nfrom .download_metrics import download_phase_metrics\n",
    "import metrics import",
)
old_import = '''                    media = import_media_file(
                        db,
                        scene=scene,
                        release_title=release_title,
                        storage_path=storage_path,
                        settings=settings,
                    )
'''
new_import = '''                    with download_phase_metrics.start(str(tracked.nzo_id), "import"):
                        media = import_media_file(
                            db,
                            scene=scene,
                            release_title=release_title,
                            storage_path=storage_path,
                            settings=settings,
                        )
'''
imports = replace_once(imports, old_import, new_import, "import phase")
import_path.write_text(imports)

bench_path = Path("tools/benchmark_0310.py")
bench = bench_path.read_text()
bench = replace_once(bench, "import time\n", "import time\nimport threading\n", "benchmark threading import")
bench = replace_once(
    bench,
    "IDLE_UI_FALLBACK_INTERVAL_SECONDS = 15\n",
    "IDLE_UI_FALLBACK_INTERVAL_SECONDS = 15\nDOWNLOAD_PIPELINE_SEGMENTS = 10_000\nDOWNLOAD_PIPELINE_WORKERS = 4\n",
    "benchmark constants",
)
scenario_code = r'''

def _one_download_pipeline_sample(temp_root: Path, sample_index: int) -> tuple[float, dict[str, object]]:
    from scarletx.download_metrics import SegmentResultBuffer, download_phase_metrics
    from scarletx.native_usenet import queue_rows

    buffer = SegmentResultBuffer(DOWNLOAD_PIPELINE_WORKERS)
    engine, session_factory = _session_factory(
        temp_root / f"download-pipeline-{sample_index}.sqlite3"
    )
    job_id = f"download-pipeline-{sample_index}"
    try:
        _seed_queue(session_factory)
        per_worker = DOWNLOAD_PIPELINE_SEGMENTS // DOWNLOAD_PIPELINE_WORKERS
        remainder = DOWNLOAD_PIPELINE_SEGMENTS % DOWNLOAD_PIPELINE_WORKERS

        def producer(worker_index: int) -> None:
            count = per_worker + (1 if worker_index < remainder else 0)
            for item_index in range(count):
                with download_phase_metrics.start(job_id, "receive"):
                    value = (worker_index, item_index)
                with download_phase_metrics.start(job_id, "decode_write"):
                    buffer.put(value)

        threads = [
            threading.Thread(target=producer, args=(index,), daemon=True)
            for index in range(DOWNLOAD_PIPELINE_WORKERS)
        ]
        started = time.perf_counter()
        for thread in threads:
            thread.start()

        api_started = time.perf_counter()
        with session_factory() as db:
            api_rows = len(queue_rows(db, limit=QUEUE_JOBS))
        api_probe_seconds = time.perf_counter() - api_started

        consumed = 0
        while consumed < DOWNLOAD_PIPELINE_SEGMENTS:
            buffer.get()
            consumed += 1
        for thread in threads:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("download pipeline benchmark producer stalled")
        elapsed = time.perf_counter() - started
        phases = download_phase_metrics.snapshot(job_id)
        return elapsed, {
            "workers": DOWNLOAD_PIPELINE_WORKERS,
            "max_buffer_size": buffer.maxsize,
            "peak_buffer_size": buffer.peak_size,
            "api_probe_seconds": api_probe_seconds,
            "api_rows": api_rows,
            "phase_names": sorted(phases),
        }
    finally:
        download_phase_metrics.clear(job_id)
        engine.dispose()


def _benchmark_download_pipeline(temp_root: Path, iterations: int) -> BenchmarkResult:
    samples: list[float] = []
    api_samples: list[float] = []
    last: dict[str, object] = {}
    for sample_index in range(iterations):
        elapsed, last = _one_download_pipeline_sample(temp_root, sample_index)
        samples.append(elapsed)
        api_samples.append(float(last["api_probe_seconds"]))
    metadata = {
        **last,
        "api_probe_seconds": statistics.median(api_samples),
        "api_probe_samples_seconds": api_samples,
        "samples_seconds": samples,
    }
    return BenchmarkResult(
        "download_pipeline",
        iterations,
        statistics.median(samples),
        DOWNLOAD_PIPELINE_SEGMENTS,
        metadata,
    )
'''
bench = replace_once(
    bench,
    "\nScenario = Callable[[Path, int], BenchmarkResult]\n",
    scenario_code + "\nScenario = Callable[[Path, int], BenchmarkResult]\n",
    "download benchmark function",
)
bench = replace_once(
    bench,
    'SCENARIOS: dict[str, Scenario] = {\n    "idle_ui": _benchmark_idle_ui,\n',
    'SCENARIOS: dict[str, Scenario] = {\n    "download_pipeline": _benchmark_download_pipeline,\n    "idle_ui": _benchmark_idle_ui,\n',
    "benchmark scenario registration",
)
bench_path.write_text(bench)

baseline_path = Path("tests/test_performance_baseline.py")
baseline = baseline_path.read_text()
baseline = replace_once(
    baseline,
    'EXPECTED_SCENARIOS = {"idle_ui", "list_api", "library_scan", "queue_reads", "tpdb_coalescing"}\n',
    'EXPECTED_SCENARIOS = {"download_pipeline", "idle_ui", "list_api", "library_scan", "queue_reads", "tpdb_coalescing"}\n',
    "expected scenarios",
)
baseline = replace_once(
    baseline,
    '    assert set(results) == EXPECTED_SCENARIOS\n\n    assert results["idle_ui"]["operations"] == 10_000\n',
    '    assert set(results) == EXPECTED_SCENARIOS\n\n    assert results["download_pipeline"]["operations"] == 10_000\n    assert results["download_pipeline"]["metadata"]["workers"] == 4\n    assert results["download_pipeline"]["metadata"]["max_buffer_size"] == 8\n    assert results["download_pipeline"]["metadata"]["peak_buffer_size"] <= 8\n    assert results["download_pipeline"]["metadata"]["api_rows"] == 200\n    assert results["download_pipeline"]["metadata"]["api_probe_seconds"] < 0.25\n    assert len(results["download_pipeline"]["metadata"]["samples_seconds"]) == 1\n\n    assert results["idle_ui"]["operations"] == 10_000\n',
    "download benchmark assertions",
)
baseline_path.write_text(baseline)
