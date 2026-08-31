from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_static_frontend_contains_auth_gate_and_account_controls():
    html = text("frontend/index.html")
    assert 'id="authGate"' in html
    assert 'id="authUsername"' in html
    assert 'id="authPassword"' in html
    assert 'id="authPasswordConfirm"' in html
    assert 'id="authAccountButton"' in html
    assert 'id="authLogoutButton"' in html
    assert 'id="authAccountDialog"' in html
    assert '<link rel="stylesheet" href="/auth.css">' in html
    assert '<script src="/auth.js"></script>' in html


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

    html = text("frontend/index.html")
    assert "authGateBoot(boot);" in html
    assert "\nboot();\n" not in html


def test_frontend_does_not_persist_scarletx_credentials_in_browser_storage():
    combined = text("frontend/index.html") + text("frontend/auth.js")
    assert 'localStorage.setItem("scarletx' not in combined
    assert "localStorage.setItem('scarletx" not in combined
    assert 'sessionStorage.setItem("scarletx' not in combined
    assert "sessionStorage.setItem('scarletx" not in combined


def test_frontend_has_no_direct_backend_address():
    combined = text("frontend/index.html") + text("frontend/auth.js")
    assert "scarletx-backend" not in combined
    assert "localhost:8000" not in combined
    assert "127.0.0.1:8000" not in combined
