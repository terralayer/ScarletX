from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_read_only_status_snapshot_is_deferred_out_of_blocking_startup():
    application = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    startup = application[application.index("async def lifespan"):application.index("app = FastAPI")]
    blocking = startup[:startup.index("await downloader_supervisor.start()")]

    assert "collect_startup_status" not in blocking
    assert "asyncio.create_task(emit_startup_status_snapshot(runtime))" in startup

    helper_path = ROOT / "scarletx" / "startup_status.py"
    assert helper_path.exists()
    helper = helper_path.read_text(encoding="utf-8")
    assert "async def emit_startup_status_snapshot" in helper
    assert "await asyncio.to_thread" in helper
    assert "collect_startup_status" in helper
