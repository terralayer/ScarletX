from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_fastapi_backend_does_not_serve_frontend_root():
    from scarletx.app import app

    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 404


def test_backend_composition_has_no_runtime_ui_injection():
    application = text("scarletx/app.py")
    assert "auth_ui" not in application
    assert "install_auth_ui" not in application
    assert not (ROOT / "scarletx/auth_ui.py").exists()
    assert not (ROOT / "scarletx/web/index.html").exists()


def test_backend_defaults_to_internal_port_8000():
    launcher = text("scarletx/__main__.py")
    dockerfile = text("Dockerfile")
    assert 'SCARLETX_PORT", "8000"' in launcher
    assert "SCARLETX_PORT=8000" in dockerfile
    assert "EXPOSE 8000" in dockerfile
    assert "127.0.0.1:8000/api/health" in dockerfile
    assert "COPY frontend" not in dockerfile


def test_nginx_is_the_public_http_entrypoint():
    config = text("nginx/scarletx.conf")
    assert "listen ${SCARLETX_WEB_PORT};" in config
    assert "root /usr/share/nginx/html;" in config
    assert "location /api/" in config
    assert "proxy_pass http://${SCARLETX_BACKEND_HOST}:${SCARLETX_BACKEND_PORT};" in config
    assert "http://scarletx-backend:8000" not in config
    assert "location = /docs" in config
    assert "location = /redoc" in config
    assert "location = /openapi.json" in config
    assert "proxy_set_header Host $host;" in config
    assert "proxy_set_header X-Real-IP $remote_addr;" in config
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" in config
    assert "proxy_set_header X-Forwarded-Proto $scarletx_forwarded_proto;" in config
    assert "location = /api/activity/stream" in config
    assert "proxy_buffering off;" in config
    assert "proxy_cache off;" in config
    assert "try_files $uri $uri/ /index.html;" in config


def test_web_image_builds_finished_static_frontend():
    web_dockerfile = text("Dockerfile.web")
    assert "FROM nginx:" in web_dockerfile
    assert "SCARLETX_WEB_PORT=8690" in web_dockerfile
    assert "SCARLETX_BACKEND_HOST=scarletx-backend" in web_dockerfile
    assert "SCARLETX_BACKEND_PORT=8000" in web_dockerfile
    assert "COPY nginx/scarletx.conf /etc/nginx/templates/default.conf.template" in web_dockerfile
    assert "COPY frontend/index.html /usr/share/nginx/html/index.html" in web_dockerfile
    assert "COPY frontend/auth.css /usr/share/nginx/html/auth.css" in web_dockerfile
    assert "COPY frontend/auth.js /usr/share/nginx/html/auth.js" in web_dockerfile
    assert "authGateBoot(boot);" in web_dockerfile
    assert "/auth.css" in web_dockerfile
    assert "/auth.js" in web_dockerfile
    assert "EXPOSE 8690" in web_dockerfile
    assert "USER 568:568" in web_dockerfile
    assert "127.0.0.1:${SCARLETX_WEB_PORT}/api/health" in web_dockerfile


def test_compose_publishes_only_nginx_web_port():
    compose = text("docker-compose.yml")
    assert "scarletx-backend:" in compose
    assert "scarletx-web:" in compose
    backend_block, web_block = compose.split("  scarletx-web:", 1)
    assert "ports:" not in backend_block
    assert 'SCARLETX_TRUST_PROXY_HEADERS: "1"' in backend_block
    assert '"${SCARLETX_WEB_PORT:-8690}:${SCARLETX_WEB_PORT:-8690}"' in web_block
    assert 'SCARLETX_WEB_PORT: "${SCARLETX_WEB_PORT:-8690}"' in web_block
    assert "scarletx-backend" in web_block


def test_container_workflow_publishes_backend_and_web_images():
    workflow = text(".github/workflows/container.yml")
    assert "ghcr.io/${{ github.repository }}" in workflow
    assert "ghcr.io/terralayer/scarletx-web" in workflow
    assert "file: Dockerfile.web" in workflow


def test_truenas_template_routes_public_port_through_nginx():
    values = text("packaging/truenas/scarletx/ix_values.yaml")
    template = text("packaging/truenas/scarletx/templates/docker-compose.yaml")
    assert "backend_image:" in values
    assert "web_image:" in values
    assert "scarletx_backend_container_name: backend" in values
    assert "scarletx_web_container_name: web" in values
    assert "backend_port: 8000" in values
    assert 'tpl.add_container(values.consts.scarletx_backend_container_name, "backend_image")' in template
    assert 'web.environment.add_env("SCARLETX_BACKEND_HOST", values.consts.scarletx_backend_container_name)' in template
    assert 'web.environment.add_env("SCARLETX_BACKEND_PORT", values.consts.backend_port)' in template


def test_truenas_containers_share_an_explicit_internal_network():
    template = text("packaging/truenas/scarletx/templates/docker-compose.yaml")
    values = text("packaging/truenas/scarletx/ix_values.yaml")
    assert "internal_network_name:" in values
    assert "tpl.networks.create_internal(values.consts.internal_network_name)" in template
    assert "backend.add_network(scarletx_net)" in template
    assert "web.add_network(scarletx_net)" in template


def test_truenas_uses_lightweight_http_healthchecks():
    template = text("packaging/truenas/scarletx/templates/docker-compose.yaml")
    assert 'backend.healthcheck.set_test("http", {"port": values.consts.backend_port, "path": "/api/health"})' in template
    assert 'web.healthcheck.set_test("http", {"port": values.network.web_port.port_number, "path": "/api/health"})' in template
    assert "set_custom_test" not in template
    assert "urllib.request" not in template


def test_truenas_environment_paths_derive_from_constants():
    template = text("packaging/truenas/scarletx/templates/docker-compose.yaml")
    assert 'backend.environment.add_env("SCARLETX_PORT", values.consts.backend_port)' in template
    assert '"sqlite:///%s/scarletx.db"|format(values.consts.config_path)' in template
    assert 'values.consts.downloads_path ~ "/incomplete"' in template
    assert 'values.consts.downloads_path ~ "/complete"' in template
    assert 'values.consts.config_path ~ "/generated"' in template
    assert 'values.consts.config_path ~ "/cache"' in template
    assert 'backend.environment.add_env("SCARLETX_DEFAULT_MEDIA_ROOT", values.consts.media_path)' in template
    assert "SCARLETX_NO_BROWSER" not in template


def test_truenas_metadata_uses_rendered_service_names():
    app = text("packaging/truenas/scarletx/app.yaml")
    questions = text("packaging/truenas/scarletx/questions.yaml")
    assert "Container [backend]" in app
    assert "Container [web]" in app
    assert "Container [scarletx-backend]" not in app
    assert "Container [scarletx-web]" not in app
    assert "- value: backend" in questions
    assert "- value: web" in questions
    assert "- value: scarletx" not in questions
