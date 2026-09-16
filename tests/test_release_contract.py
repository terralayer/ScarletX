from pathlib import Path
import importlib.util
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCKED_VERSION = "0.4.6"


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def project_version(root: Path = ROOT) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


VERSION = project_version()


def load_release_version_module():
    path = ROOT / "tools" / "release_version.py"
    spec = importlib.util.spec_from_file_location("scarletx_release_version", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_is_locked_to_046_everywhere():
    assert VERSION == LOCKED_VERSION
    assert f'version = "{LOCKED_VERSION}"' in text("pyproject.toml")
    assert f'__version__ = "{LOCKED_VERSION}"' in text("scarletx/__init__.py")
    assert f'version="{LOCKED_VERSION}"' in text("scarletx/routes/application.py")
    assert f'"version": "{LOCKED_VERSION}"' in text("scarletx/routes/application.py")
    assert f"Current application version: **{LOCKED_VERSION}**." in text("README.md")
    assert f"ScarletX {LOCKED_VERSION}" in text("BUILD-INFO.txt")
    assert (ROOT / f"RELEASE-NOTES-{LOCKED_VERSION}.md").exists()


def test_truenas_metadata_and_compose_are_locked_to_046():
    app = text("packaging/truenas/scarletx/app.yaml")
    values = text("packaging/truenas/scarletx/ix_values.yaml")
    compose = text("docker-compose.truenas.yml")

    assert f"app_version: {LOCKED_VERSION}" in app
    assert re.search(r"(?m)^version: \d+\.\d+\.\d+$", app)
    assert "changelog_url: https://github.com/terralayer/ScarletX/releases" in app
    assert re.search(rf"(?m)^\s+tag: {re.escape(LOCKED_VERSION)}$", values)
    assert f"image: ghcr.io/terralayer/scarletx:{LOCKED_VERSION}" in compose
    assert f"image: ghcr.io/terralayer/scarletx-web:{LOCKED_VERSION}" in compose
    assert 'SCARLETX_PORT: "8000"' in compose
    assert 'SCARLETX_WEB_PORT: ${SCARLETX_PORT:-8690}' in compose

    for role in ("permissions", "backend", "web"):
        expected = f"scarletx-{LOCKED_VERSION}-{role}"
        assert f"container_name: {expected}" in compose
        assert f"_container_name: {expected}" in values


def test_main_container_publishing_never_overwrites_stable_release_tags():
    workflow = text(".github/workflows/container.yml")
    assert "type=raw,value=0.4.6" not in workflow
    assert "type=raw,value=main" in workflow
    assert "type=sha,prefix=sha-" in workflow
    assert "type=semver" not in workflow
    assert 'tags: ["v*"]' not in workflow


def test_release_workflow_selects_only_locked_046_and_tags_tested_head():
    workflow = text(".github/workflows/release.yml")
    assert "workflow_dispatch:" in workflow
    assert "NEXT_VERSION=\"0.4.6\"" in workflow
    assert "Select locked release version" in workflow
    assert "Apply locked 0.4.6 release metadata" in workflow
    assert "version is locked and will not advance" in workflow
    assert "ghcr.io/terralayer/scarletx:${NEXT_VERSION}" in workflow
    assert "ghcr.io/terralayer/scarletx-web:${NEXT_VERSION}" in workflow
    assert "git checkout --detach origin/main" not in workflow
    assert 'git tag -a "v${NEXT_VERSION}" -m "ScarletX ${NEXT_VERSION}" HEAD' in workflow


def test_release_helper_rejects_versions_after_046():
    module = load_release_version_module()
    assert module.LOCKED_RELEASE_VERSION == LOCKED_VERSION
    assert module.next_patch_version("0.4.5") == LOCKED_VERSION
    assert module.next_release_version("0.4.6-beta.1") == LOCKED_VERSION

    for current in ("0.4.6", "0.4.7", "0.4.9", "0.4.99"):
        with pytest.raises(ValueError, match="locked at 0.4.6"):
            module.next_patch_version(current)

    for current in ("0.4.7-beta.1", "0.4.9-beta.2"):
        with pytest.raises(ValueError, match="locked at 0.4.6"):
            module.next_release_version(current)


def test_outbound_user_agents_report_locked_version():
    for path in (
        "scarletx/tpdb.py",
        "scarletx/remote_art.py",
        "scarletx/newznab.py",
        "scarletx/usenet/worker.py",
    ):
        assert f"ScarletX/{LOCKED_VERSION}" in text(path), f"{path} has a stale User-Agent"


def test_release_declares_agplv3_license():
    assert 'license = "AGPL-3.0-only"' in text("pyproject.toml")
    license_text = text("LICENSE")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text
    assert "Version 3, 19 November 2007" in license_text
    assert "AGPL-3.0-only" in text("README.md")


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


def test_truenas_test_values_do_not_inject_undocumented_environment_variables():
    test_values = ROOT / "packaging" / "truenas" / "scarletx" / "templates" / "test_values"
    for path in test_values.glob("*.yaml"):
        contents = path.read_text(encoding="utf-8")
        assert "SCARLETX_TEST_MODE" not in contents, f"{path.name} injects an undocumented environment variable"


def test_truenas_basic_values_follow_community_block_order():
    contents = text("packaging/truenas/scarletx/templates/test_values/basic-values.yaml")
    top_level_keys = re.findall(r"(?m)^([a-z][a-z0-9_]*):", contents)
    assert top_level_keys == [
        "resources",
        "scarletx",
        "network",
        "run_as",
        "ix_volumes",
        "storage",
        "labels",
    ]


def test_actions_use_current_generations():
    tests = text(".github/workflows/tests.yml")
    container = text(".github/workflows/container.yml")
    assert "actions/checkout@v5" in tests
    assert "actions/setup-python@v6" in tests
    for required in (
        "docker/setup-buildx-action@v4",
        "docker/login-action@v4",
        "docker/metadata-action@v6",
        "docker/build-push-action@v7",
    ):
        assert required in container


def test_release_notes_stay_out_of_runtime_backend_image():
    dockerfile = text("Dockerfile")
    assert "RELEASE-NOTES-*.md" not in dockerfile
    assert (ROOT / "RELEASE-NOTES-0.4.6.md").exists()


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
