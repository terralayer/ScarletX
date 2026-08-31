from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.db import Base
from scarletx.http_security import install_authentication, install_security_headers


def make_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()

    @app.get("/")
    def root():
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": "ScarletX"}

    @app.get("/api/private")
    def private():
        return {"private": True}

    settings = SimpleNamespace(api_key_enabled=False, api_key=SecretStr(""))
    install_authentication(app, session_factory=factory, settings_loader=lambda _db: settings)
    install_security_headers(app)
    return TestClient(app)


def assert_security_headers(response):
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_security_headers_apply_to_normal_and_auth_failure_responses():
    client = make_client()
    root = client.get("/")
    protected = client.get("/api/private")
    assert root.status_code == 200
    assert protected.status_code == 401
    assert_security_headers(root)
    assert_security_headers(protected)


def test_auth_and_setup_responses_are_not_cacheable():
    client = make_client()
    auth = client.get("/api/auth/status")
    setup = client.get("/api/setup/status")
    assert auth.headers["cache-control"] == "no-store"
    assert setup.headers["cache-control"] == "no-store"
