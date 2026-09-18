from tests.test_auth_routes import make_client, PASSWORD
from tests.test_auth_middleware import make_app, create_admin
from scarletx.settings_store import load_database_settings


def test_setup_enables_auth_and_persists_generated_key():
    client, factory = make_client()
    first = client.get('/api/setup/api-key')
    assert first.status_code == 200
    key = first.json()['api_key']
    assert len(key) >= 43
    assert client.get('/api/setup/api-key').json()['api_key'] != key
    payload = dict(username='admin', password=PASSWORD, password_confirm=PASSWORD, api_key=key)
    assert client.post('/api/setup/admin', json=payload).status_code == 200
    with factory() as db:
        settings = load_database_settings(db)
        assert settings.ui_auth_enabled and settings.api_key_enabled
        assert settings.api_key.get_secret_value() == key
    assert client.get('/api/setup/api-key').status_code == 409
    assert client.post('/api/setup/admin', json=payload).status_code == 409


def test_private_requests_require_authentication():
    client, factory = make_app(ui_auth_enabled=True, api_key_enabled=True, api_key='test-automation-key')
    assert client.get('/api/private').status_code == 403
    token = create_admin(factory)
    assert client.get('/api/private').status_code == 401
    assert client.get('/api/private?apikey=test-automation-key').status_code == 401
    assert client.get('/api/private', headers={'X-Api-Key':'wrong'}).status_code == 401
    assert client.get('/api/private', headers={'X-Api-Key':'test-automation-key'}).status_code == 200
    assert client.get('/api/private', headers={'Authorization':'Bearer test-automation-key'}).status_code == 200
    client.cookies.set('scarletx_session', token)
    assert client.get('/api/private').status_code == 200


def test_setup_rejects_missing_or_weak_key_without_creating_admin():
    client, _factory = make_client()
    for key in ['', 'short', 'a' * 42]:
        response = client.post('/api/setup/admin', json=dict(username='admin', password=PASSWORD, password_confirm=PASSWORD, api_key=key))
        assert response.status_code == 422
        assert client.get('/api/setup/status').json()['setup_required']


def test_account_change_requires_browser_session_even_with_legacy_flag_disabled():
    client, _factory = make_client()
    response = client.patch('/api/auth/admin', json=dict(username='intruder', password=PASSWORD, password_confirm=PASSWORD))
    assert response.status_code == 401
    assert client.get('/api/setup/status').json()['setup_required']


def test_cross_origin_mutation_rejected():
    client, factory = make_app(ui_auth_enabled=True)
    client.cookies.set('scarletx_session', create_admin(factory))
    assert client.post('/api/private', headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/setup/admin', headers={'Origin':'null'}).status_code == 403
    assert client.post('/api/auth/login', headers={'Sec-Fetch-Site':'cross-site'}).status_code == 403
