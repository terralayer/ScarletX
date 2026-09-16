from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_release_discipline_policy_tracks_current_release_lock():
    version = _project_version()
    policy = (ROOT / "docs" / "RELEASE-DISCIPLINE.md").read_text(encoding="utf-8")
    assert f"current shipped release lock remains `{version}`" in policy.casefold()


def test_release_workflow_requires_explicit_manual_dispatch():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    trigger_block = workflow.split("concurrency:", 1)[0]
    assert "workflow_dispatch:" in trigger_block
    assert "\n  push:" not in trigger_block
