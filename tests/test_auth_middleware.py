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


def make_app(*, ui_auth_enabled=False, api_key_enabled=False, api_key="", raise_server_exceptions=True):
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

    @app.get("/api/activity/stream")
    def activity_stream():
        return {"stream": True}

    @app.get("/api/crash")
    def crash():
        raise RuntimeError("downstream failure")

    settings = SimpleNamespace(
        ui_auth_enabled=ui_auth_enabled,
        api_key_enabled=api_key_enabled,
        api_key=SecretStr(api_key),
    )
    install_authentication(app, session_factory=factory, settings_loader=lambda _db: settings)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), factory


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


def test_private_api_is_open_when_ui_auth_is_disabled():
    client, factory = make_app(ui_auth_enabled=False)
    assert client.get("/api/private").status_code == 200
    create_admin(factory)
    assert client.get("/api/private").status_code == 200


def test_private_api_stays_open_when_ui_auth_setting_is_enabled():
    client, factory = make_app(ui_auth_enabled=True)
    assert client.get("/api/private").status_code == 200
    create_admin(factory)
    assert client.get("/api/private").status_code == 200


def test_activity_stream_does_not_require_authenticated_session():
    client, factory = make_app(ui_auth_enabled=True)
    create_admin(factory)

    assert client.get("/api/activity/stream").status_code == 200


def test_existing_browser_session_does_not_change_private_api_access():
    client, factory = make_app(ui_auth_enabled=True)
    token = create_admin(factory)
    client.cookies.set("scarletx_session", token)
    assert client.get("/api/private").status_code == 200


def test_api_access_no_longer_depends_on_api_key():
    client, factory = make_app(ui_auth_enabled=True, api_key_enabled=True, api_key="automation-key")
    create_admin(factory)
    assert client.get("/api/private", headers={"X-Api-Key": "automation-key"}).status_code == 200
    assert client.get("/api/private", headers={"Authorization": "Bearer automation-key"}).status_code == 200
    assert client.get("/api/private?apikey=automation-key").status_code == 200
    assert client.get("/api/private", headers={"X-Api-Key": "wrong"}).status_code == 200


def test_non_api_spa_shell_remains_public():
    client, _factory = make_app(ui_auth_enabled=True)
    response = client.get("/")
    assert response.status_code == 404


def test_framework_docs_and_openapi_are_public_without_session_gate():
    client, _factory = make_app(ui_auth_enabled=True)
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_downstream_failure_is_not_misreported_as_auth_outage():
    client, _factory = make_app(ui_auth_enabled=True, raise_server_exceptions=False)

    response = client.get("/api/crash")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"


def test_production_bootstrap_registers_auth_routes_and_removes_legacy_api_key_middleware():
    import scarletx.app as application
    from scarletx import main

    production_app = application.app
    assert production_app is main.app
    assert str(production_app.url_path_for("auth_status")) == "/api/auth/status"
    assert str(production_app.url_path_for("setup_admin")) == "/api/setup/admin"

    dispatch_names = {
        getattr(getattr(item, "kwargs", {}).get("dispatch"), "__name__", "")
        for item in production_app.user_middleware
    }
    assert "optional_api_key_auth" not in dispatch_names
