from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.models import NativeUsenetJob, TrackedDownload

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_hotfix_is_installed_from_composed_app():
    entrypoint = (ROOT / "scarletx" / "app.py").read_text(encoding="utf-8")
    composition = (ROOT / "scarletx" / "runtime_composition.py").read_text(encoding="utf-8")
    assert "install_runtime_composition" in entrypoint
    assert "install_downloader_state_hotfixes(app)" in composition


def test_hotfix_repairs_retry_and_reprocess_state():
    source = (ROOT / "scarletx" / "downloader_state_hotfix.py").read_text(encoding="utf-8")
    assert 'tracked.status = "queued"' in source
    assert 'tracked.client_status = "queued"' in source
    assert "native_queue_signal.notify()" in source
    assert 'tracked.status == "import_failed"' in source
    assert 'tracked.status = "import_pending"' in source


def test_hotfix_serializes_duplicate_native_enqueue():
    source = (ROOT / "scarletx" / "downloader_state_hotfix.py").read_text(encoding="utf-8")
    assert "_ENQUEUE_LOCK" in source
    assert "with _ENQUEUE_LOCK:" in source
    assert "download_clients.enqueue_url = enqueue_url_hotfix" in source


def test_hotfix_keeps_paused_job_paused_before_worker_claim():
    source = (ROOT / "scarletx" / "downloader_state_hotfix.py").read_text(encoding="utf-8")
    assert "async def process_job_hotfix" in source
    assert 'if job.status == "paused":' in source
    assert "worker.process_job = process_job_hotfix" in source


def test_pause_all_stops_only_transfers_and_keeps_processing_jobs_running():
    from scarletx.downloader_state_hotfix import pause_all_native_downloads

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)
    with session() as db:
        db.add_all([
            NativeUsenetJob(id="queued", title="Queued", nzb_url="https://example.invalid/q", status="queued"),
            NativeUsenetJob(id="downloading", title="Downloading", nzb_url="https://example.invalid/d", status="downloading"),
            NativeUsenetJob(id="processing", title="Processing", nzb_url="https://example.invalid/p", status="postprocessing"),
            TrackedDownload(nzo_id="queued", release_title="Queued", status="queued", client_status="queued"),
            TrackedDownload(nzo_id="downloading", release_title="Downloading", status="downloading", client_status="downloading"),
        ])
        db.commit()

        result = pause_all_native_downloads(db)

        statuses = {job.id: job.status for job in db.scalars(select(NativeUsenetJob)).all()}
        tracked = {job.nzo_id: (job.status, job.client_status) for job in db.scalars(select(TrackedDownload)).all()}

    assert result == {"paused": 2, "global_paused": True}
    assert statuses == {"queued": "paused", "downloading": "paused", "processing": "postprocessing"}
    assert tracked == {"queued": ("paused", "paused"), "downloading": ("paused", "paused")}
