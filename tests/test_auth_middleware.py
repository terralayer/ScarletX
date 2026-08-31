from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.auth import create_session, hash_password
from scarletx.db import Base
from scarletx.http_security import install_authentication
from scarletx.models import AuthUser


def make_app(*, api_key_enabled=False, api_key=""):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "ScarletX"}

    @app.get("/api/private")
    def private():
        return {"private": True}

    settings = SimpleNamespace(
        api_key_enabled=api_key_enabled,
        api_key=SecretStr(api_key),
    )
    install_authentication(app, session_factory=factory, settings_loader=lambda _db: settings)
    return TestClient(app), factory


def create_admin(factory):
    with factory() as db:
        user = AuthUser(
            id=1,
            username="admin",
            username_normalized="admin",
            password_hash=hash_password("correct-horse-battery"),
        )
        db.add(user)
        db.commit()
        return create_session(db, user.id)


def test_health_remains_anonymous_during_first_run():
    client, _factory = make_app()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["app"] == "ScarletX"


def test_private_api_is_blocked_during_setup_and_after_setup_without_auth():
    client, factory = make_app()
    assert client.get("/api/private").status_code == 401
    create_admin(factory)
    assert client.get("/api/private").status_code == 401


def test_valid_browser_session_authenticates_private_api():
    client, factory = make_app()
    token = create_admin(factory)
    client.cookies.set("scarletx_session", token)
    assert client.get("/api/private").status_code == 200


def test_existing_api_key_authenticates_when_enabled():
    client, factory = make_app(api_key_enabled=True, api_key="automation-key")
    create_admin(factory)
    assert client.get("/api/private", headers={"X-Api-Key": "automation-key"}).status_code == 200
    assert client.get("/api/private", headers={"Authorization": "Bearer automation-key"}).status_code == 200
    assert client.get("/api/private?apikey=automation-key").status_code == 200
    assert client.get("/api/private", headers={"X-Api-Key": "wrong"}).status_code == 401


def test_non_api_spa_shell_remains_public():
    client, _factory = make_app()
    response = client.get("/")
    assert response.status_code == 404
