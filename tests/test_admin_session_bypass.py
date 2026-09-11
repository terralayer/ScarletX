from pathlib import Path

from tests.test_auth_middleware import make_app


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_boot_does_not_check_administrator_session():
    script = (ROOT / "frontend" / "auth.js").read_text(encoding="utf-8")

    assert "/api/auth/status" not in script
    assert "Checking security" not in script
    assert "Verifying the local ScarletX administrator session." not in script
    assert "window.authGateBoot" in script
    assert "showOpenApp();" in script


def test_existing_ui_auth_setting_does_not_require_browser_session():
    client, _factory = make_app(ui_auth_enabled=True)

    assert client.get("/api/private").status_code == 200
    assert client.get("/api/activity/stream").status_code == 200
    assert client.get("/openapi.json").status_code == 200
