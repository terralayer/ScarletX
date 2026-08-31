from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_is_consistent():
    assert 'version = "0.3.7"' in text("pyproject.toml")
    app = text("packaging/truenas/scarletx/app.yaml")
    values = text("packaging/truenas/scarletx/ix_values.yaml")
    assert "app_version: 0.3.7" in app
    assert "version: 1.0.1" in app
    assert "RELEASE-NOTES-0.3.7.md" in app
    assert re.search(r"(?m)^\s+tag: 0\.3\.7$", values)
    assert (ROOT / "RELEASE-NOTES-0.3.7.md").exists()


def test_main_does_not_publish_a_numeric_stable_tag():
    workflow = text(".github/workflows/container.yml")
    assert "type=raw,value=0.3.7,enable={{is_default_branch}}" not in workflow
    assert "type=semver,pattern={{version}}" in workflow


def test_truenas_validation_covers_application_changes():
    workflow = text(".github/workflows/truenas-validation.yml")
    for required in (
        '"scarletx/**"',
        '"pyproject.toml"',
        '"requirements*.txt"',
        '"Dockerfile"',
        '"packaging/truenas/**"',
    ):
        assert required in workflow


def test_truenas_full_deploy_is_release_tag_only():
    workflow = text(".github/workflows/truenas-validation.yml")
    assert 'tags: ["v*"]' in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert 'RELEASE_VERSION="${GITHUB_REF_NAME#v}"' in workflow
    assert "ghcr.io/terralayer/scarletx:${RELEASE_VERSION}" in workflow


def test_actions_use_current_node24_generations():
    tests = text(".github/workflows/tests.yml")
    assert "actions/checkout@v5" in tests
    assert "actions/setup-python@v6" in tests
    assert "actions/checkout@v4" not in tests
    assert "actions/setup-python@v5" not in tests


def test_container_actions_use_node24_generations():
    workflow = text(".github/workflows/container.yml")
    for required in (
        "docker/setup-buildx-action@v4",
        "docker/login-action@v4",
        "docker/metadata-action@v6",
        "docker/build-push-action@v7",
    ):
        assert required in workflow
    for deprecated in (
        "docker/setup-buildx-action@v3",
        "docker/login-action@v3",
        "docker/metadata-action@v5",
        "docker/build-push-action@v6",
    ):
        assert deprecated not in workflow


def test_container_includes_current_release_notes():
    dockerfile = text("Dockerfile")
    assert "RELEASE-NOTES-*.md" in dockerfile
    assert "RELEASE-NOTES-0.3.6.md" not in dockerfile
