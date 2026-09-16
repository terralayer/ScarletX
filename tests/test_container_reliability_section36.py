from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_health_contract_is_present_in_all_compose_deployments():
    for name in ("docker-compose.yml", "docker-compose.truenas.yml"):
        compose = (ROOT / name).read_text(encoding="utf-8")
        backend = compose[compose.index("  scarletx-backend:"):compose.index("  scarletx-web:")]
        web = compose[compose.index("  scarletx-web:"):]

        assert "healthcheck:" in backend, name
        assert "http://127.0.0.1:8000/api/health" in backend, name
        assert "timeout=3" in backend, name
        assert "interval: 30s" in backend, name
        assert "timeout: 5s" in backend, name
        assert "start_period: 30s" in backend, name
        assert "retries: 3" in backend, name
        assert "scarletx-backend:\n        condition: service_healthy" in web, name
