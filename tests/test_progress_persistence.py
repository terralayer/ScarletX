from __future__ import annotations

import inspect
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from scarletx.db import Base
from scarletx.models import NativeUsenetJob


MIB = 1024 * 1024


class FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _gate_class():
    from scarletx.progress import ProgressCheckpointGate

    return ProgressCheckpointGate


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'progress.sqlite3'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed_job(session_factory, job_id: str, *, status: str = "downloading", downloaded: int = 0) -> None:
    with session_factory() as db:
        db.add(
            NativeUsenetJob(
                id=job_id,
                title="Checkpoint test",
                nzb_url="https://example.invalid/test.nzb",
                status=status,
                total_bytes=64 * MIB,
                downloaded_bytes=downloaded,
                speed_bps=0.0,
            )
        )
        db.commit()


def test_progress_persists_at_most_once_per_interval():
    ProgressCheckpointGate = _gate_class()
    gate = ProgressCheckpointGate(interval_seconds=2.0, byte_threshold=8 * MIB)
    clock = FakeClock()

    assert gate.should_persist("job", 1, clock())
    clock.advance(1.9)
    assert not gate.should_persist("job", 2, clock())
    clock.advance(0.1)
    assert gate.should_persist("job", 3, clock())


def test_progress_persists_after_byte_threshold_before_interval():
    ProgressCheckpointGate = _gate_class()
    gate = ProgressCheckpointGate(interval_seconds=2.0, byte_threshold=8 * MIB)
    clock = FakeClock()

    assert gate.should_persist("job", 0, clock())
    clock.advance(0.1)
    assert not gate.should_persist("job", 8 * MIB - 1, clock())
    assert gate.should_persist("job", 8 * MIB, clock())


def test_force_makes_the_next_progress_update_durable():
    ProgressCheckpointGate = _gate_class()
    gate = ProgressCheckpointGate(interval_seconds=2.0, byte_threshold=8 * MIB)

    assert gate.should_persist("job", 100, 0.0)
    assert not gate.should_persist("job", 101, 0.1)
    gate.force("job")
    assert gate.should_persist("job", 101, 0.1)


def test_clear_resets_checkpoint_history():
    ProgressCheckpointGate = _gate_class()
    gate = ProgressCheckpointGate(interval_seconds=2.0, byte_threshold=8 * MIB)

    assert gate.should_persist("job", 100, 0.0)
    assert not gate.should_persist("job", 101, 0.1)
    gate.clear("job")
    assert gate.should_persist("job", 101, 0.1)


def test_publish_progress_owns_checkpoint_decision():
    from scarletx.native_usenet import _publish_progress

    assert "persist" not in inspect.signature(_publish_progress).parameters


def test_queue_reads_keep_live_values_between_durable_checkpoints(tmp_path, monkeypatch):
    from scarletx import native_usenet

    engine, Session = _session_factory(tmp_path)
    job_id = "live-values"
    _seed_job(Session, job_id)
    native_usenet._clear_live_progress(job_id)
    if hasattr(native_usenet, "_PROGRESS_CHECKPOINT_GATE"):
        native_usenet._PROGRESS_CHECKPOINT_GATE.clear(job_id)

    clock = FakeClock()
    monkeypatch.setattr(native_usenet.time, "monotonic", clock)
    try:
        native_usenet._publish_progress(
            Session,
            job_id,
            total_bytes=64 * MIB,
            downloaded_bytes=1 * MIB,
            speed_bps=10 * MIB,
            eta_seconds=6,
        )
        clock.advance(0.5)
        native_usenet._publish_progress(
            Session,
            job_id,
            total_bytes=64 * MIB,
            downloaded_bytes=2 * MIB,
            speed_bps=11 * MIB,
            eta_seconds=5,
        )

        with Session() as db:
            stored = db.get(NativeUsenetJob, job_id)
            row = native_usenet.job_dict(stored)
            assert stored.downloaded_bytes == 1 * MIB
            assert row["downloaded_bytes"] == 2 * MIB
            assert row["speed_bps"] == 11 * MIB
            assert row["eta_seconds"] == 5
    finally:
        native_usenet._clear_live_progress(job_id)
        engine.dispose()


def test_terminal_transition_forces_latest_live_progress_before_clear(tmp_path):
    from scarletx import native_usenet

    engine, Session = _session_factory(tmp_path)
    job_id = "terminal-flush"
    _seed_job(Session, job_id, downloaded=1 * MIB)
    native_usenet._clear_live_progress(job_id)
    try:
        native_usenet._set_live_progress(
            job_id,
            total_bytes=64 * MIB,
            downloaded_bytes=23 * MIB,
            speed_bps=7 * MIB,
            eta_seconds=4,
        )
        native_usenet._set_job(Session, job_id, status="completed")
        native_usenet._clear_live_progress(job_id)

        with Session() as db:
            stored = db.get(NativeUsenetJob, job_id)
            assert stored.status == "completed"
            assert stored.total_bytes == 64 * MIB
            assert stored.downloaded_bytes == 23 * MIB
            assert stored.speed_bps == 7 * MIB
            assert stored.eta_seconds == 4
    finally:
        native_usenet._clear_live_progress(job_id)
        engine.dispose()


def test_pause_route_flushes_latest_live_progress(tmp_path):
    from scarletx import native_usenet
    from scarletx.main import pause_native_download

    engine, Session = _session_factory(tmp_path)
    job_id = "pause-flush"
    _seed_job(Session, job_id, downloaded=1 * MIB)
    native_usenet._clear_live_progress(job_id)
    try:
        native_usenet._set_live_progress(
            job_id,
            total_bytes=64 * MIB,
            downloaded_bytes=17 * MIB,
            speed_bps=5 * MIB,
            eta_seconds=9,
        )
        with Session() as db:
            response = pause_native_download(job_id, db=db)
            assert response["status"] == "paused"
        native_usenet._clear_live_progress(job_id)

        with Session() as db:
            stored = db.get(NativeUsenetJob, job_id)
            assert stored.status == "paused"
            assert stored.downloaded_bytes == 17 * MIB
            assert stored.speed_bps == 5 * MIB
            assert stored.eta_seconds == 9
    finally:
        native_usenet._clear_live_progress(job_id)
        engine.dispose()


def test_cancel_route_flushes_latest_live_progress(tmp_path):
    from scarletx import native_usenet
    from scarletx.main import cancel_native_download

    engine, Session = _session_factory(tmp_path)
    job_id = "cancel-flush"
    _seed_job(Session, job_id, downloaded=1 * MIB)
    native_usenet._clear_live_progress(job_id)
    settings = SimpleNamespace(native_usenet_incomplete_dir=str(tmp_path / "incomplete"))
    try:
        native_usenet._set_live_progress(
            job_id,
            total_bytes=64 * MIB,
            downloaded_bytes=19 * MIB,
            speed_bps=6 * MIB,
            eta_seconds=8,
        )
        with Session() as db:
            response = cancel_native_download(job_id, db=db, settings=settings)
            assert response["downloaded_bytes"] == 19 * MIB
        native_usenet._clear_live_progress(job_id)

        with Session() as db:
            stored = db.get(NativeUsenetJob, job_id)
            assert stored.cancel_requested is True
            assert stored.downloaded_bytes == 19 * MIB
            assert stored.speed_bps == 6 * MIB
            assert stored.eta_seconds == 8
    finally:
        native_usenet._clear_live_progress(job_id)
        engine.dispose()


def test_thousand_small_updates_use_bounded_checkpoint_writes(tmp_path, monkeypatch):
    from scarletx import native_usenet

    engine, Session = _session_factory(tmp_path)
    job_id = "bounded-writes"
    _seed_job(Session, job_id)
    native_usenet._clear_live_progress(job_id)
    gate = getattr(native_usenet, "_PROGRESS_CHECKPOINT_GATE", None)
    if gate is not None:
        gate.clear(job_id)

    writes = 0

    def count_progress_updates(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal writes
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("update native_usenet_jobs set"):
            writes += 1

    event.listen(engine, "before_cursor_execute", count_progress_updates)
    clock = FakeClock()
    monkeypatch.setattr(native_usenet.time, "monotonic", clock)
    try:
        for index in range(1_000):
            clock.value = index * 0.0005
            native_usenet._publish_progress(
                Session,
                job_id,
                total_bytes=128 * MIB,
                downloaded_bytes=(index + 1) * 64 * 1024,
                speed_bps=20 * MIB,
                eta_seconds=3,
            )
        assert writes == 8
    finally:
        event.remove(engine, "before_cursor_execute", count_progress_updates)
        native_usenet._clear_live_progress(job_id)
        engine.dispose()
