from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_uses_supported_test_client_dependency_and_local_json_response():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    application = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")

    assert '"httpx2>=2.13,<3"' in pyproject
    assert "BlockingPortal alias is deprecated" in pyproject
    assert "class ScarletJSONResponse(Response)" in application
    assert "default_response_class=ScarletJSONResponse" in application
    assert "ORJSONResponse" not in application


def test_slow_auth_test_sets_session_on_client_instead_of_per_request():
    source = (ROOT / "tests" / "test_performance_049.py").read_text(encoding="utf-8")

    assert "client.cookies.set('scarletx_session', token)" in source
    assert "client.get('/api/private', cookies=" not in source
