import asyncio
import threading
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from scarletx.auth import LoginLimiter, revoke_session
from scarletx.http_security import install_authentication
from scarletx.settings_store import load_database_settings, set_setting
from tests.test_auth_middleware import create_admin
from tests.test_auth_routes import make_client


def authenticated_app():
    _, factory = make_client()
    token = create_admin(factory)
    app = FastAPI()
    loads = []

    def settings_loader(db, **kwargs):
        loads.append(kwargs)
        return load_database_settings(db, **kwargs)

    @app.get('/api/private')
    async def private():
        return {'ok': True}

    @app.get('/api/health')
    async def health():
        return {'ok': True}

    install_authentication(app, session_factory=factory, settings_loader=settings_loader)
    return app, factory, token, loads


def test_browser_session_skips_settings_and_revocation_is_immediate():
    app, factory, token, loads = authenticated_app()
    client = TestClient(app)
    client.cookies.set('scarletx_session', token)
    assert client.get('/api/private').status_code == 200
    assert loads == []
    with factory() as db:
        revoke_session(db, token)
    assert client.get('/api/private').status_code == 401


def test_api_key_rotation_bypasses_stale_settings_cache():
    app, factory, _, loads = authenticated_app()
    client = TestClient(app)
    with factory() as db:
        set_setting(db, 'api_key_enabled', 'true')
        set_setting(db, 'api_key', 'old-key')
    assert client.get('/api/private', headers={'X-Api-Key':'old-key'}).status_code == 200
    with factory() as db:
        set_setting(db, 'api_key', 'new-key')
    assert client.get('/api/private', headers={'X-Api-Key':'old-key'}).status_code == 401
    assert client.get('/api/private', headers={'X-Api-Key':'new-key'}).status_code == 200
    assert all(call.get('force') for call in loads)


@pytest.mark.asyncio
async def test_slow_auth_database_does_not_stall_health():
    app, factory, token, _ = authenticated_app()
    started = threading.Event()
    engine = factory.kw['bind']

    @event.listens_for(engine, 'before_cursor_execute')
    def slow_read(*_):
        started.set()
        time.sleep(.15)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', cookies={'scarletx_session':token}) as client:
        start = time.monotonic()
        task = asyncio.create_task(client.get('/api/private'))
        while not started.is_set():
            await asyncio.sleep(.001)
        response = await client.get('/api/health')
        elapsed = time.monotonic() - start
        assert (await task).status_code == 200
        assert response.status_code == 200
        assert elapsed < .1, f'Health blocked behind auth for {elapsed:.3f}s'


def test_limiter_does_not_allocate_for_successful_checks_and_expires_idle_addresses(monkeypatch):
    now = [0.0]
    monkeypatch.setattr('scarletx.auth.time.monotonic', lambda: now[0])
    limiter = LoginLimiter(window_seconds=10)
    for i in range(200):
        assert not limiter.is_blocked(str(i))
    assert not limiter._events
    for i in range(200):
        limiter.record_failure(str(i))
    now[0] = 11
    assert not limiter.is_blocked('fresh')
    assert not limiter._events


def test_limiter_capacity_preserves_existing_blocks(monkeypatch):
    now = [0.0]
    monkeypatch.setattr('scarletx.auth.time.monotonic', lambda: now[0])
    limiter = LoginLimiter(max_failures=2, window_seconds=10, max_addresses=3)
    for address in ['a', 'b', 'c']:
        for _ in range(20):
            limiter.record_failure(address)
    assert len(limiter._events) == 3
    assert all(len(events) <= 2 for events in limiter._events.values())
    assert limiter.is_blocked('a')
    assert limiter.is_blocked('new')
    limiter.record_failure('new')
    assert len(limiter._events) == 3
    now[0] = 11
    assert not limiter.is_blocked('new')
