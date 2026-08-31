from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_static_auth_assets_contain_gate_and_account_controls():
    script = text("frontend/auth.js")
    styles = text("frontend/auth.css")
    assert 'id="authGate"' in script
    assert 'id="authUsername"' in script
    assert 'id="authPassword"' in script
    assert 'id="authPasswordConfirm"' in script
    assert 'id="authAccountButton"' in script
    assert 'id="authLogoutButton"' in script
    assert 'id="authAccountDialog"' in script
    assert ".sx-auth-gate" in styles
    assert ".sx-auth-account" in styles


def test_static_auth_script_uses_same_origin_api_and_gates_app_boot():
    script = text("frontend/auth.js")
    for endpoint in (
        "/api/auth/status",
        "/api/setup/admin",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/auth/admin",
    ):
        assert endpoint in script
    assert "credentials:'same-origin'" in script or 'credentials: "same-origin"' in script
    assert "window.authGateBoot" in script


def test_web_image_injects_static_auth_assets_and_delays_legacy_boot():
    web_dockerfile = text("Dockerfile.web")
    assert "/auth.css" in web_dockerfile
    assert "/auth.js" in web_dockerfile
    assert "authGateBoot(boot);" in web_dockerfile


def test_frontend_does_not_persist_scarletx_credentials_in_browser_storage():
    combined = text("scarletx/web/index.html") + text("frontend/auth.js")
    assert 'localStorage.setItem("scarletx' not in combined
    assert "localStorage.setItem('scarletx" not in combined
    assert 'sessionStorage.setItem("scarletx' not in combined
    assert "sessionStorage.setItem('scarletx" not in combined


def test_frontend_has_no_direct_backend_address():
    combined = text("scarletx/web/index.html") + text("frontend/auth.js")
    assert "scarletx-backend" not in combined
    assert "localhost:8000" not in combined
    assert "127.0.0.1:8000" not in combined
