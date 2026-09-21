from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.auth import SESSION_COOKIE_NAME, login_limiter, session_user
from scarletx.auth_routes import (
    SETUP_AGREEMENT_ACCEPTED_AT_KEY,
    SETUP_AGREEMENT_VERSION_KEY,
    router,
)
from scarletx.db import Base, get_session
from scarletx.models import AppSetting, AuthSession, AuthUser

PASSWORD = "correct-horse-battery"


def make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)

    def override_session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), factory


def accept_agreement(client):
    status = client.get("/api/setup/agreement").json()
    if status["required"]:
        response = client.post(
            "/api/setup/agreement",
            json={"accepted": True, "version": status["current_version"]},
        )
        assert response.status_code == 200
        return response.json()
    return status


def setup_admin(client, username="admin", password=PASSWORD, *, accept_agreement_first=True):
    if accept_agreement_first:
        accept_agreement(client)
    return client.post(
        "/api/setup/admin",
        json={
            "username": username,
            "password": password,
            "password_confirm": password,
            "api_key": "a" * 43,
        },
    )


def test_first_run_setup_creates_one_admin_and_logs_in():
    client, factory = make_client()
    assert client.get("/api/setup/status").json() == {"setup_required": True}
    agreement = client.get("/api/setup/agreement").json()
    assert agreement["required"] is True
    assert agreement["accepted"] is False

    response = setup_admin(client)
    assert response.status_code == 200
    assert response.json()["username"] == "admin"
    cookie = response.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    assert client.get("/api/setup/status").json() == {"setup_required": False}
    assert client.get("/api/auth/status").json() == {
        "enabled": True,
        "setup_required": False,
        "agreement_required": False,
        "authenticated": True,
        "username": "admin",
    }

    with factory() as db:
        assert db.scalar(select(AuthUser)).password_hash != PASSWORD
        stored_session = db.scalar(select(AuthSession))
        assert stored_session is not None
        raw = client.cookies.get(SESSION_COOKIE_NAME)
        assert raw != stored_session.token_digest
        assert session_user(db, raw).username == "admin"


def test_admin_setup_is_blocked_until_usage_agreement_is_recorded():
    client, factory = make_client()

    response = setup_admin(client, accept_agreement_first=False)
    assert response.status_code == 428
    assert "agreement" in response.json()["detail"].lower()
    with factory() as db:
        assert db.scalar(select(AuthUser.id)) is None

    before = client.get("/api/setup/agreement").json()
    assert before["required"] is True
    assert before["accepted_at"] is None
    accepted = client.post(
        "/api/setup/agreement",
        json={"accepted": True, "version": before["current_version"]},
    )
    assert accepted.status_code == 200
    saved = accepted.json()
    assert saved["required"] is False
    assert saved["accepted"] is True
    assert saved["accepted_at"].endswith("Z")

    repeated = client.post(
        "/api/setup/agreement",
        json={"accepted": True, "version": before["current_version"]},
    )
    assert repeated.status_code == 200
    assert repeated.json()["accepted_at"] == saved["accepted_at"]

    with factory() as db:
        assert db.get(AppSetting, SETUP_AGREEMENT_ACCEPTED_AT_KEY).value == saved["accepted_at"]
        assert db.get(AppSetting, SETUP_AGREEMENT_VERSION_KEY).value == saved["version"]

    assert setup_admin(client, accept_agreement_first=False).status_code == 200


def test_second_admin_creation_is_rejected():
    client, _factory = make_client()
    assert setup_admin(client).status_code == 200
    response = setup_admin(client, username="second", password="another-long-password")
    assert response.status_code == 409


def test_login_uses_generic_failure_and_rate_limits_client():
    client, _factory = make_client()
    assert setup_admin(client).status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    login_limiter.clear("testclient")

    unknown = client.post(
        "/api/auth/login",
        json={"username": "not-admin", "password": "wrong-password"},
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == "Invalid username or password"

    login_limiter.clear("testclient")
    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": PASSWORD},
    )
    assert blocked.status_code == 429
    login_limiter.clear("testclient")

    success = client.post(
        "/api/auth/login",
        json={"username": "ADMIN", "password": PASSWORD},
    )
    assert success.status_code == 200
    assert success.json()["username"] == "admin"


def test_logout_revokes_current_session():
    client, factory = make_client()
    assert setup_admin(client).status_code == 200
    raw = client.cookies.get(SESSION_COOKIE_NAME)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert SESSION_COOKIE_NAME not in client.cookies
    with factory() as db:
        assert session_user(db, raw) is None


def test_password_change_revokes_old_sessions_and_issues_replacement():
    client, factory = make_client()
    assert setup_admin(client).status_code == 200
    old_token = client.cookies.get(SESSION_COOKIE_NAME)

    response = client.patch(
        "/api/auth/admin",
        json={
            "username": "ScarletAdmin",
            "password": "new-correct-horse-battery",
            "password_confirm": "new-correct-horse-battery",
        },
    )
    assert response.status_code == 200
    assert response.json()["username"] == "ScarletAdmin"
    new_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert new_token and new_token != old_token

    with factory() as db:
        assert session_user(db, old_token) is None
        assert session_user(db, new_token).username == "ScarletAdmin"

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login",
        json={"username": "scarletadmin", "password": "new-correct-horse-battery"},
    ).status_code == 200
