from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from scarletx.auth_ui import install_auth_ui, render_auth_shell


def test_auth_shell_delays_legacy_boot_and_exposes_setup_login_logout_controls():
    legacy = "<html><body><div id='legacy'>legacy</div><script>function boot(){}\nboot();\n</script></body></html>"

    rendered = render_auth_shell(legacy)

    assert "authGate" in rendered
    assert "authUsername" in rendered
    assert "authPassword" in rendered
    assert "authPasswordConfirm" in rendered
    assert "authAccountButton" in rendered
    assert "authLogoutButton" in rendered
    assert "authAccountDialog" in rendered
    assert "/api/auth/status" in rendered
    assert "/api/setup/admin" in rendered
    assert "/api/auth/login" in rendered
    assert "/api/auth/logout" in rendered
    assert "/api/auth/admin" in rendered
    assert "authGateBoot(boot);" in rendered
    assert "\nboot();\n" not in rendered


def test_auth_shell_rendering_is_idempotent():
    legacy = "<html><body><script>function boot(){}\nboot();\n</script></body></html>"
    once = render_auth_shell(legacy)
    twice = render_auth_shell(once)
    assert twice == once


def test_auth_ui_middleware_only_replaces_root_html(tmp_path: Path):
    html_path = tmp_path / "index.html"
    html_path.write_text(
        "<html><body><script>function boot(){}\nboot();\n</script></body></html>",
        encoding="utf-8",
    )
    app = FastAPI()

    @app.get("/")
    def root():
        return HTMLResponse("legacy root")

    @app.get("/plain")
    def plain():
        return HTMLResponse("plain")

    install_auth_ui(app, html_path=html_path)
    client = TestClient(app)

    root = client.get("/")
    assert root.status_code == 200
    assert "authGate" in root.text
    assert root.headers["cache-control"] == "no-store"

    plain = client.get("/plain")
    assert plain.status_code == 200
    assert plain.text == "plain"


def test_production_root_uses_auth_shell_and_security_headers():
    from scarletx.app import app as production_app

    client = TestClient(production_app)
    response = client.get("/")

    assert response.status_code == 200
    assert "authGate" in response.text
    assert "authGateBoot(boot);" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
