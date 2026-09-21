from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_static_frontend_is_outside_backend_package():
    assert (ROOT / "frontend/index.html").exists()
    assert not (ROOT / "scarletx/web/index.html").exists()


def test_static_auth_assets_do_not_render_bottom_account_controls():
    script = text("frontend/auth.js")
    styles = text("frontend/auth.css")
    assert 'id="authGate"' in script
    assert 'id="authUsername"' in script
    assert 'id="authPassword"' in script
    assert 'id="authAccountButton"' not in script
    assert 'id="authLogoutButton"' not in script
    assert 'id="authAccountDialog"' not in script
    assert 'id="authGate" aria-live="polite"' in script
    assert ".sx-auth-gate" in styles
    assert ".sx-auth-account" not in styles


def test_static_auth_script_uses_same_origin_login_api_without_bottom_account_actions():
    script = text("frontend/auth.js")
    assert "/api/auth/login" in script
    assert "/api/auth/logout" not in script
    assert "/api/auth/admin" not in script
    assert "/api/auth/status" in script
    assert "credentials:'same-origin'" in script or 'credentials: "same-origin"' in script
    assert "window.authGateBoot" in script


def test_auth_gate_boots_application_immediately_without_session_check():
    script = text("frontend/auth.js")
    assert "showOpenApp();" in script
    assert "Checking security" not in script
    assert "Verifying the local ScarletX administrator session." not in script
    assert "/api/setup/admin" in script
    assert "/api/setup/agreement" in script
    assert 'id="authAgreementScroll"' in script
    assert 'id="authAgreementAccept"' in script
    assert 'id="authAgreementContinue"' in script
    assert "Scroll to the bottom to enable acceptance." in script


def test_activity_queue_refresh_waits_until_the_auth_gate_opens_the_app():
    auth = text("frontend/auth.js")
    overrides = text("frontend/ui_overrides.js")

    assert "dispatchQueue('scarletx:app-open')" in auth
    assert "window.addEventListener('scarletx:app-open', refreshActivityQueueTotal)" in overrides
    assert "refreshActivityQueueTotal();\n\nfunction mediaFileRowsHtml" not in overrides


def test_pre_auth_session_expiry_does_not_reload_the_setup_gate():
    script = text("frontend/auth.js")

    assert "const gate = document.getElementById('authGate');" in script
    assert "if (gate && !gate.hidden) return;" in script
    assert "window.addEventListener('scarletx:session-expired', () => location.reload());" not in script


def test_security_settings_expose_ui_auth_credentials():
    script = text("frontend/app.js")
    assert "ui_auth_enabled" in script
    assert 'id="securityUsername"' in script
    assert 'id="securityPassword"' in script
    assert 'id="securityPasswordConfirm"' in script


def test_web_image_injects_static_auth_assets_and_boots_through_shim():
    web_dockerfile = text("Dockerfile.web")
    assert "COPY frontend/index.html /usr/share/nginx/html/index.html" in web_dockerfile
    assert "/auth.css" in web_dockerfile
    assert "/auth.js" in web_dockerfile
    assert "authGateBoot(boot);" in web_dockerfile


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
