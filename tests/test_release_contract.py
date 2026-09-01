from pathlib import Path
import importlib.util
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def project_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


VERSION = project_version()


def load_release_version_module():
    path = ROOT / "tools" / "release_version.py"
    assert path.exists(), "tools/release_version.py is required for the permanent release workflow"
    spec = importlib.util.spec_from_file_location("scarletx_release_version", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_version_is_consistent():
    assert VERSION.startswith("0.3.")
    assert f'version = "{VERSION}"' in text("pyproject.toml")
    app = text("packaging/truenas/scarletx/app.yaml")
    values = text("packaging/truenas/scarletx/ix_values.yaml")
    assert f"app_version: {VERSION}" in app
    assert "version: 1.0.2" in app
    assert f"RELEASE-NOTES-{VERSION}.md" in app
    assert re.search(rf"(?m)^\s+tag: {re.escape(VERSION)}$", values)
    assert "ghcr.io/terralayer/scarletx-web" in values
    assert (ROOT / f"RELEASE-NOTES-{VERSION}.md").exists()


def test_shipped_application_metadata_reports_current_version():
    expected_by_file = {
        "scarletx/__init__.py": f'__version__ = "{VERSION}"',
        "scarletx/main.py": f'version="{VERSION}"',
        "README.md": f"Current application version: **{VERSION}**.",
        "BUILD-INFO.txt": f"ScarletX {VERSION}",
        "start-scarletx.sh": f"ScarletX {VERSION}",
        "Start-ScarletX.ps1": f"ScarletX {VERSION}",
        "docker-compose.truenas.yml": f"image: ghcr.io/terralayer/scarletx:{VERSION}",
    }
    for path, expected in expected_by_file.items():
        assert expected in text(path), f"{path} does not report {VERSION}"

    truenas_compose = text("docker-compose.truenas.yml")
    assert f"image: ghcr.io/terralayer/scarletx-web:{VERSION}" in truenas_compose
    assert 'SCARLETX_PORT: "8000"' in truenas_compose
    assert 'SCARLETX_WEB_PORT: ${SCARLETX_PORT:-8690}' in truenas_compose
    assert f'"version": "{VERSION}"' in text("scarletx/main.py")
    assert f"RELEASE-NOTES-{VERSION}.md" in text("README.md")


def test_outbound_user_agents_report_current_version():
    for path in (
        "scarletx/tpdb.py",
        "scarletx/remote_art.py",
        "scarletx/newznab.py",
        "scarletx/native_usenet.py",
    ):
        assert f"ScarletX/{VERSION}" in text(path), f"{path} has a stale User-Agent"


def test_release_declares_agplv3_license():
    assert 'license = "AGPL-3.0-only"' in text("pyproject.toml")
    license_text = text("LICENSE")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text
    assert "AGPL-3.0-only" in text("README.md")


def test_main_does_not_publish_a_numeric_stable_tag():
    workflow = text(".github/workflows/container.yml")
    assert f"type=raw,value={VERSION},enable={{{{is_default_branch}}}}" not in workflow
    assert "type=semver,pattern={{version}}" in workflow


def test_truenas_validation_covers_application_changes():
    workflow = text(".github/workflows/truenas-validation.yml")
    for required in (
        '"scarletx/**"',
        '"frontend/**"',
        '"nginx/**"',
        '"pyproject.toml"',
        '"requirements*.txt"',
        '"Dockerfile"',
        '"Dockerfile.web"',
        '"packaging/truenas/**"',
    ):
        assert required in workflow


def test_truenas_full_deploy_is_release_tag_only():
    workflow = text(".github/workflows/truenas-validation.yml")
    assert 'tags: ["v*"]' in workflow
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert 'RELEASE_VERSION="${GITHUB_REF_NAME#v}"' in workflow
    assert "ghcr.io/terralayer/scarletx:${RELEASE_VERSION}" in workflow
    assert "ghcr.io/terralayer/scarletx-web:${RELEASE_VERSION}" in workflow


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


def test_release_version_calculator_only_increments_third_component():
    module = load_release_version_module()
    assert module.next_patch_version("0.3.8") == "0.3.9"
    assert module.next_patch_version("0.3.9") == "0.3.10"
    assert module.next_patch_version("0.3.99") == "0.3.100"

    for invalid in ("0.4.0", "1.3.8", "0.3", "0.3.8.1", "v0.3.8"):
        with pytest.raises(ValueError):
            module.next_patch_version(invalid)


def test_release_apply_updates_versioned_files_and_creates_notes(tmp_path):
    module = load_release_version_module()
    current = "0.3.8"
    expected = "0.3.9"

    for relative_path in module.VERSIONED_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_path == "pyproject.toml":
            path.write_text(
                f'[project]\nname = "scarletx"\nversion = "{current}"\n',
                encoding="utf-8",
            )
        else:
            path.write_text(f"release marker {current}\n", encoding="utf-8")

    next_version = module.apply_release(tmp_path, "Maintenance release notes.")
    assert next_version == expected
    for relative_path in module.VERSIONED_FILES:
        updated = (tmp_path / relative_path).read_text(encoding="utf-8")
        assert current not in updated
        assert expected in updated

    notes = (tmp_path / f"RELEASE-NOTES-{expected}.md").read_text(encoding="utf-8")
    assert notes.startswith(f"# ScarletX {expected}\n")
    assert "Maintenance release notes." in notes


def test_permanent_release_workflow_is_manual_and_uses_patch_calculator():
    workflow = text(".github/workflows/release.yml")
    assert "workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow
    assert "tools/release_version.py" in workflow
    assert "NEXT_VERSION" in workflow
    assert "ghcr.io/terralayer/scarletx:${NEXT_VERSION}" in workflow
    assert "ghcr.io/terralayer/scarletx-web:${NEXT_VERSION}" in workflow
    assert "RELEASE-NOTES-${NEXT_VERSION}.md" in workflow


def test_readme_documents_two_container_nginx_deployment():
    readme = text("README.md")
    for required in (
        "scarletx-backend",
        "scarletx-web",
        "ghcr.io/terralayer/scarletx:main",
        "ghcr.io/terralayer/scarletx-web:main",
        "port `8000`",
        "Nginx",
    ):
        assert required in readme
    assert f"Current application version: **{VERSION}**." in readme
