from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_helper_has_no_hardcoded_current_version_lock():
    source = (ROOT / "tools" / "release_version.py").read_text(encoding="utf-8")
    assert "LOCKED_RELEASE_VERSION" not in source
    assert "release version is locked at" not in source.casefold()


def test_main_container_metadata_does_not_publish_numeric_default_branch_tag():
    workflow = (ROOT / ".github" / "workflows" / "container.yml").read_text(encoding="utf-8")
    assert "type=raw,value=0.4.4,enable={{is_default_branch}}" not in workflow


def test_roadmap_release_discipline_requires_separate_release_pr():
    policy = (ROOT / "docs" / "release-discipline.md").read_text(encoding="utf-8")
    normalized = " ".join(policy.casefold().split())
    assert "version changes must be isolated in a dedicated release pull request" in normalized
    assert "roadmap pull requests must not bump the application version" in normalized
