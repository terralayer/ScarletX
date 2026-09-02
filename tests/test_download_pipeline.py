from __future__ import annotations

import json
import queue
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE_SOURCE = ROOT / "scarletx" / "native_usenet.py"
IMPORT_SOURCE = ROOT / "scarletx" / "download_processing.py"
EXPECTED_PHASES = {
    "receive",
    "decode_write",
    "verify",
    "repair",
    "extract",
    "probe",
    "import",
}


def test_phase_metrics_record_only_bounded_non_secret_telemetry():
    from scarletx.download_metrics import DownloadPhaseMetrics, PHASES

    assert set(PHASES) == EXPECTED_PHASES
    metrics = DownloadPhaseMetrics()
    with pytest.raises(RuntimeError, match="provider password"):
        with metrics.start("job-a", "receive"):
            raise RuntimeError("provider password=do-not-record")

    snapshot = metrics.snapshot("job-a")
    encoded = json.dumps(snapshot, sort_keys=True)
    assert snapshot["receive"]["count"] == 1
    assert snapshot["receive"]["failures"] == 1
    assert snapshot["receive"]["total_seconds"] >= 0
    assert "do-not-record" not in encoded
    assert "password" not in encoded.casefold()


def test_segment_result_buffer_is_bounded_to_twice_worker_count():
    from scarletx.download_metrics import SegmentResultBuffer

    buffer = SegmentResultBuffer(worker_count=4)
    assert buffer.maxsize == 8
    for index in range(8):
        buffer.put_nowait(index)
    assert buffer.peak_size == 8
    with pytest.raises(queue.Full):
        buffer.put_nowait(9)
    assert [buffer.get_nowait() for _ in range(8)] == list(range(8))


def test_pipeline_integrates_bounded_results_and_all_explicit_phases():
    native = NATIVE_SOURCE.read_text(encoding="utf-8")
    imports = IMPORT_SOURCE.read_text(encoding="utf-8")

    assert "SegmentResultBuffer(" in native
    assert "download_phase_metrics.start(job_id, \"receive\")" in native
    assert "download_phase_metrics.start(job_id, \"decode_write\")" in native
    for phase in ("verify", "repair", "extract", "probe"):
        assert f'download_phase_metrics.start(job_id, "{phase}")' in native
    assert 'download_phase_metrics.start(str(tracked.nzo_id), "import")' in imports


def test_cancellation_preserves_recoverable_partial_work_for_retry():
    source = NATIVE_SOURCE.read_text(encoding="utf-8")
    start = source.rfind("except asyncio.CancelledError:")
    assert start >= 0
    end = source.find("except Exception as exc:", start)
    cancelled = source[start:end]

    assert "shutil.rmtree(work" not in cancelled
    assert "partial data preserved" in cancelled.casefold()
    assert "output_path=str(work) if work.exists() else None" in cancelled


def test_provider_pool_reuses_released_connection(monkeypatch):
    from scarletx import native_usenet as native

    created = []

    class DummyConnection:
        def __init__(self, provider):
            self.provider = provider
            self.closed = False
            created.append(self)

        def close(self):
            self.closed = True

        def abort(self):
            self.closed = True

    monkeypatch.setattr(native, "NNTPConnection", DummyConnection)
    provider = native.UsenetProviderConfig(name="primary", host="news.invalid", connections=1)
    pool = native._ProviderConnectionPool(provider)

    first = pool.acquire()
    pool.release(first)
    second = pool.acquire()

    assert second is first
    assert len(created) == 1
    pool.release(second)
    pool.close()


def test_segment_retry_budget_is_total_not_per_provider(monkeypatch, tmp_path):
    from scarletx import native_usenet as native

    attempts = []

    class DummyConnection:
        def __init__(self, provider):
            self.provider = provider

        def body_iter(self, _message_id):
            return iter((b"=ybegin line=128 size=1 name=x.bin", b"k", b"=yend size=1"))

        def close(self):
            return None

        def abort(self):
            return None

    def failing_decode(*_args, **_kwargs):
        attempts.append(1)
        raise RuntimeError("wire failure")

    monkeypatch.setattr(native, "NNTPConnection", DummyConnection)
    monkeypatch.setattr(native, "decode_yenc_to_target", failing_decode)
    providers = [
        native.UsenetProviderConfig(name="a", host="a.invalid", connections=1),
        native.UsenetProviderConfig(name="b", host="b.invalid", connections=1),
    ]
    fetcher = native.SegmentFetcher(providers, max_retries=2)
    fetcher.native_acceleration = False
    segment = native.NZBSegment(number=1, bytes=1, message_id="segment@test")

    with pytest.raises(native.NativeUsenetError, match="wire failure"):
        fetcher.fetch_into(
            segment,
            tmp_path / "assembly.part",
            tmp_path / "000001.done",
        )

    assert len(attempts) == 4
    fetcher.close()


def test_crc_failure_is_rejected_without_leaving_partial_file(tmp_path):
    from scarletx.native_usenet import NativeUsenetError, decode_yenc_to_file

    target = tmp_path / "bad.bin"
    rows = (
        b"=ybegin line=128 size=1 name=bad.bin",
        b"k",
        b"=yend size=1 pcrc32=00000000",
    )
    with pytest.raises(NativeUsenetError, match="CRC mismatch"):
        decode_yenc_to_file(rows, target)

    assert not target.with_name("bad.bin.part").exists()


def test_repair_timeout_kills_tool_and_surfaces_bounded_error(monkeypatch, tmp_path):
    from scarletx import native_usenet as native

    class TimedOutProcess:
        returncode = -9

        def __init__(self):
            self.killed = False
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if timeout is not None and self.calls == 1:
                raise subprocess.TimeoutExpired(cmd="par2", timeout=timeout)
            return ("partial output", None)

        def kill(self):
            self.killed = True

        def poll(self):
            return None if not self.killed else self.returncode

    process = TimedOutProcess()
    monkeypatch.setattr(native.subprocess, "Popen", lambda *_args, **_kwargs: process)

    with pytest.raises(native.NativeUsenetError, match="timed out"):
        native._run_tool(["par2", "v", "sample.par2"], tmp_path, 1, job_id="job-timeout", label="PAR2 verification")

    assert process.killed is True


def test_corrupt_zip_extraction_fails_without_masking_error(tmp_path):
    from scarletx.native_usenet import NativeUsenetError, unpack_payload

    (tmp_path / "broken.zip").write_bytes(b"not-a-zip")
    with pytest.raises(NativeUsenetError, match="Could not unpack"):
        unpack_payload(tmp_path, enabled=True, job_id="job-extract")


def test_import_failure_path_remains_retryable():
    source = IMPORT_SOURCE.read_text(encoding="utf-8")
    assert "except (FileImportError, MetadataProviderError) as exc:" in source
    failure_block = source[source.index("except (FileImportError, MetadataProviderError) as exc:") :]
    assert 'tracked.status = "import_pending"' in failure_block
