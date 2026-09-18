from tests.test_auth_middleware import make_app, create_admin


def test_legacy_disabled_setting_does_not_bypass_authentication():
    client, factory = make_app(ui_auth_enabled=False)
    assert client.get('/api/private').status_code == 403
    create_admin(factory)
    assert client.get('/api/private').status_code == 401
