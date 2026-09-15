import json
from importlib.metadata import version as package_version

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_runtime_observability_records_request_and_database_metrics():
    from scarletx.observability import RuntimeObservability

    metrics = RuntimeObservability(slow_query_ms=10)
    metrics.record_request("GET", "/api/scenes", 200, 0.100)
    metrics.record_request("POST", "/api/scenes", 500, 0.200)
    metrics.record_db_query("SELECT id FROM scenes WHERE title = 'private title'", 0.005)
    metrics.record_db_query("SELECT password_hash FROM auth_users WHERE username = 'admin'", 0.020)

    snapshot = metrics.snapshot()

    assert snapshot["requests"]["count"] == 2
    assert snapshot["requests"]["errors"] == 1
    assert snapshot["requests"]["avg_ms"] == 150.0
    assert snapshot["requests"]["max_ms"] == 200.0
    assert snapshot["database"]["count"] == 2
    assert snapshot["database"]["slow_count"] == 1
    assert snapshot["database"]["avg_ms"] == 12.5
    assert snapshot["database"]["max_ms"] == 20.0

    slow = snapshot["database"]["recent_slow_queries"]
    assert len(slow) == 1
    assert slow[0]["operation"] == "SELECT"
    assert slow[0]["table"] == "auth_users"
    assert slow[0]["duration_ms"] == 20.0
    serialized = json.dumps(slow)
    assert "admin" not in serialized
    assert "password_hash" not in serialized
    assert "private title" not in serialized


def test_runtime_observability_bounds_slow_query_history():
    from scarletx.observability import RuntimeObservability

    metrics = RuntimeObservability(slow_query_ms=1, slow_query_history=3)
    for index in range(5):
        metrics.record_db_query(f"SELECT id FROM scenes WHERE id = {index}", 0.010 + index / 1000)

    slow = metrics.snapshot()["database"]["recent_slow_queries"]
    assert len(slow) == 3
    assert [item["duration_ms"] for item in slow] == [12.0, 13.0, 14.0]


def test_runtime_observability_distinguishes_tpdb_network_and_cache_latency():
    from scarletx.observability import RuntimeObservability

    metrics = RuntimeObservability()
    metrics.record_tpdb(0.050, success=True, cache="network")
    metrics.record_tpdb(0.001, success=True, cache="memory")
    metrics.record_tpdb(0.060, success=False, cache="network")
    metrics.record_tpdb(0.002, success=True, cache="disk")

    snapshot = metrics.snapshot()["tpdb"]
    assert snapshot["network_requests"] == 2
    assert snapshot["network_failures"] == 1
    assert snapshot["network_avg_ms"] == 55.0
    assert snapshot["network_max_ms"] == 60.0
    assert snapshot["cache_hits"] == {"memory": 1, "disk": 1}


def test_install_observability_records_request_and_query_once_when_installed_twice():
    from scarletx.observability import install_observability, runtime_observability

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    engine = create_engine("sqlite:///:memory:")
    before = runtime_observability.snapshot()

    install_observability(app, engine)
    install_observability(app, engine)

    response = TestClient(app).get("/ping")
    assert response.status_code == 200
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1

    after = runtime_observability.snapshot()
    assert after["requests"]["count"] - before["requests"]["count"] == 1
    assert after["database"]["count"] - before["database"]["count"] == 1


def test_system_metrics_endpoint_reports_operational_runtime_state():
    from scarletx.db import Base, get_session
    from scarletx.models import NativeUsenetJob
    from scarletx.observability_routes import router

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(
            NativeUsenetJob(
                id=1,
                title="Active scene",
                nzb_url="https://example.invalid/scene.nzb",
                status="downloading",
                speed_bps=2048.0,
            )
        )
        db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_session():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    response = TestClient(app).get("/api/system/metrics")
    assert response.status_code == 200
    payload = response.json()

    assert set(payload) == {
        "requests",
        "database",
        "tpdb",
        "queues",
        "downloads",
        "imports",
        "process",
        "disk",
    }
    assert payload["queues"]["native"]["downloading"] == 1
    assert payload["downloads"]["active_speed_bps"] == 2048.0
    assert payload["process"]["uptime_seconds"] >= 0
    assert payload["process"]["cpu_seconds"] >= 0
    assert payload["disk"]["total_bytes"] >= payload["disk"]["free_bytes"] > 0


def test_health_contract_stays_lightweight_and_matches_package_version():
    from scarletx.app import app

    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app": "ScarletX",
        "version": package_version("scarletx"),
        "upstream": "SceneCore 0.7.16",
    }
