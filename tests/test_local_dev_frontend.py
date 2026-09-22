from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_launcher_serves_current_frontend_source():
    launcher = (ROOT / "start-scarletx.sh").read_text(encoding="utf-8")
    local_dev = (ROOT / "scarletx" / "local_dev.py").read_text(encoding="utf-8")

    assert "scarletx.local_dev:app" in launcher
    assert 'echo "ScarletX 0.5.0-dev-2"' in launcher
    assert 'FRONTEND = ROOT / "frontend"' in local_dev
    assert 'StaticFiles(directory=str(FRONTEND), html=True)' in local_dev
    assert '"/app.js"' in local_dev
    assert '"authGateBoot(boot);"' in local_dev
    assert '"Cache-Control": "no-store"' in local_dev


def test_production_backend_boundary_stays_unchanged():
    boundary = (ROOT / "tests" / "test_nginx_boundary.py").read_text(encoding="utf-8")
    assert "test_fastapi_backend_does_not_serve_frontend_root" in boundary
    assert "scarletx.local_dev" not in (ROOT / "Dockerfile").read_text(encoding="utf-8")
