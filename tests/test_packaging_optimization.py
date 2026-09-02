from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def service_block(compose: str, service: str) -> str:
    match = re.search(rf"^  {re.escape(service)}:\n(?P<body>(?:    .*\n|\n)*)", compose, re.MULTILINE)
    assert match, service
    return match.group("body")


def test_runtime_images_pin_base_images_by_digest():
    backend = source("Dockerfile").splitlines()[0]
    web = source("Dockerfile.web").splitlines()[0]
    assert backend.startswith("FROM python:3.12-slim-bookworm@sha256:")
    assert web.startswith("FROM nginx:alpine@sha256:")


def test_backend_runtime_keeps_required_repair_extract_and_probe_tools():
    dockerfile = source("Dockerfile")
    for package in ("par2", "p7zip-full", "ffmpeg"):
        assert package in dockerfile
    assert "unrar ||" in dockerfile
    assert "unrar-free" in dockerfile


def test_runtime_backend_does_not_copy_release_documentation():
    dockerfile = source("Dockerfile")
    assert "COPY README.md" not in dockerfile
    assert "RELEASE-NOTES-*.md" not in dockerfile
    assert "BUILD-INFO.txt ./" not in dockerfile


def test_runtime_images_remain_non_root_and_health_checked():
    backend = source("Dockerfile")
    web = source("Dockerfile.web")
    assert "USER 568:568" in backend
    assert "USER 568:568" in web
    assert "HEALTHCHECK" in backend
    assert "/api/health" in backend
    assert "HEALTHCHECK" in web
    assert "/api/health" in web


def test_local_compose_exposes_only_web_and_uses_internal_network():
    compose = source("docker-compose.yml")
    backend = service_block(compose, "scarletx-backend")
    web = service_block(compose, "scarletx-web")
    assert "ports:" not in backend
    assert "ports:" in web
    assert "scarletx-net" in backend
    assert "scarletx-net" in web
    assert "internal: true" in compose


def test_standalone_truenas_compose_exposes_only_web_and_uses_internal_network():
    compose = source("docker-compose.truenas.yml")
    backend = service_block(compose, "scarletx-backend")
    web = service_block(compose, "scarletx-web")
    assert "ports:" not in backend
    assert "ports:" in web
    assert "scarletx-net" in backend
    assert "scarletx-net" in web
    assert "internal: true" in compose


def test_web_backend_target_is_explicitly_configurable_in_compose_files():
    for path in ("docker-compose.yml", "docker-compose.truenas.yml"):
        compose = source(path)
        web = service_block(compose, "scarletx-web")
        assert "SCARLETX_BACKEND_HOST" in web
        assert "SCARLETX_BACKEND_PORT" in web


def test_required_persistent_mounts_remain_on_backend_deployments():
    for path in ("docker-compose.yml", "docker-compose.truenas.yml"):
        backend = service_block(source(path), "scarletx-backend")
        for mount in ("/config", "/downloads", "/media", "/backups"):
            assert mount in backend


def test_truenas_template_keeps_backend_private_on_internal_network():
    template = source("packaging/truenas/scarletx/templates/docker-compose.yaml")
    assert 'create_internal("scarletx-net")' in template
    assert "backend.add_network(scarletx_net)" in template
    assert "web.add_network(scarletx_net)" in template
    assert "backend.add_port" not in template
    assert "web.add_port" in template
    assert 'web.environment.add_env("SCARLETX_BACKEND_HOST"' in template
    assert 'web.environment.add_env("SCARLETX_BACKEND_PORT"' in template


def test_release_gate_validates_compose_tools_and_records_image_sizes_before_publish():
    workflow = source(".github/workflows/release.yml")
    publish = workflow.index("Publish candidate release images")
    assert "docker compose config" in workflow[:publish]
    assert "command -v par2" in workflow[:publish]
    assert "command -v ffprobe" in workflow[:publish]
    assert "command -v 7z" in workflow[:publish]
    assert "command -v unrar" in workflow[:publish]
    assert "docker image inspect" in workflow[:publish]


def test_release_gate_retains_anonymous_pull_and_truenas_deploy_checks():
    workflow = source(".github/workflows/release.yml")
    assert "Verify anonymous release image pulls" in workflow
    assert "Deploy and health-check through TrueNAS CI" in workflow
