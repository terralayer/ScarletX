# ScarletX 0.3.7 Release and CI Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release ScarletX 0.3.7 as an immutable versioned container, make version metadata consistent, ensure all application changes trigger TrueNAS validation, and remove deprecated Node-runtime GitHub Actions.

**Architecture:** `main` remains the rolling development channel and publishes only `main` plus commit-SHA tags. Stable numeric container tags are created only from matching `vX.Y.Z` Git tags. A release-contract test prevents version drift between Python metadata, TrueNAS metadata, image references, release notes, and workflow behavior.

**Tech Stack:** GitHub Actions, Docker Buildx, GHCR, Python/pytest, TrueNAS Community Apps packaging.

**Spec:** Approved ScarletX hardening roadmap in the project conversation; authentication was Stage 1 and this is the immediately following release/CI stage.

## Global Constraints

- Release version is exactly `0.3.7` and Git tag is exactly `v0.3.7`.
- `main` must never republish a numeric stable tag.
- `ghcr.io/terralayer/scarletx:0.3.7` must be produced only by tag `v0.3.7`.
- `ghcr.io/terralayer/scarletx:main` remains the rolling image.
- TrueNAS `app_version` becomes `0.3.7`; catalog `version` becomes `1.0.1`.
- TrueNAS image reference becomes `0.3.7`.
- TrueNAS validation must trigger for `scarletx/**`, Python dependency metadata, Docker files, packaging, and relevant workflows.
- Existing Python 3.11/3.12/3.13 tests remain required.
- Replace Node-20 GitHub action generations with current Node-24-compatible generations where available.
- Keep the public `/api/health` contract intact.

---

### Task 1: Add an enforceable release contract

**Files:**
- Create: `tests/test_release_contract.py`

**Interfaces:**
- Consumes repository text files only.
- Produces CI assertions that version metadata is synchronized and stable numeric image tags are tag-only.

- [ ] **Step 1: Write failing tests**

```python
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


def test_actions_use_current_node24_generations():
    tests = text(".github/workflows/tests.yml")
    assert "actions/checkout@v5" in tests
    assert "actions/setup-python@v6" in tests
    assert "actions/checkout@v4" not in tests
    assert "actions/setup-python@v5" not in tests
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_release_contract.py -q`
Expected: failures for 0.3.7 metadata, stable-tag workflow behavior, TrueNAS path coverage, and old GitHub Action generations.

- [ ] **Step 3: Commit the red test**

Commit message: `Add release contract regression tests`.

---

### Task 2: Harden GitHub Actions and TrueNAS validation

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `.github/workflows/container.yml`
- Modify: `.github/workflows/truenas-validation.yml`

**Interfaces:**
- Produces rolling `main`/SHA images from main pushes.
- Produces semantic-version image tags from `v*` tags.
- Runs TrueNAS render validation on pull requests and full deployment validation on main/tag contexts after the required image is available.

- [ ] **Step 1: Update test actions**

Use `actions/checkout@v5` and `actions/setup-python@v6`; retain the Python 3.11/3.12/3.13 matrix and existing commands.

- [ ] **Step 2: Make container tags immutable**

Metadata tags must be:

```yaml
tags: |
  type=raw,value=main,enable={{is_default_branch}}
  type=semver,pattern={{version}}
  type=sha,prefix=sha-
```

A main push therefore cannot overwrite `0.3.7`; `v0.3.7` produces `0.3.7`.

- [ ] **Step 3: Expand TrueNAS workflow path filters**

Both `pull_request.paths` and `push.paths` must include:

```yaml
- "scarletx/**"
- "pyproject.toml"
- "requirements*.txt"
- "Dockerfile"
- "packaging/truenas/**"
- ".github/workflows/container.yml"
- ".github/workflows/truenas-validation.yml"
```

- [ ] **Step 4: Stop hard-coding the old image version in validation**

Use `0.3.7` for the release validation image. Keep render-only validation on PRs and full anonymous-pull/deployment checks on non-PR runs.

- [ ] **Step 5: Run focused release-contract tests**

Run: `python -m pytest tests/test_release_contract.py -q`.
Expected: only version-metadata tests remain red until Task 3.

- [ ] **Step 6: Commit**

Commit message: `Harden release and TrueNAS CI workflows`.

---

### Task 3: Prepare ScarletX 0.3.7 metadata and release notes

**Files:**
- Modify: `pyproject.toml`
- Modify: `packaging/truenas/scarletx/app.yaml`
- Modify: `packaging/truenas/scarletx/ix_values.yaml`
- Create: `RELEASE-NOTES-0.3.7.md`

**Interfaces:**
- Python package version, TrueNAS app version, and container image version all resolve to `0.3.7`.

- [ ] **Step 1: Bump Python version**

Set `[project].version = "0.3.7"`.

- [ ] **Step 2: Bump TrueNAS metadata**

Set:

```yaml
app_version: 0.3.7
version: 1.0.1
changelog_url: https://github.com/terralayer/ScarletX/blob/main/RELEASE-NOTES-0.3.7.md
```

- [ ] **Step 3: Bump TrueNAS image**

Set `images.image.tag: 0.3.7` in `ix_values.yaml`.

- [ ] **Step 4: Add release notes**

`RELEASE-NOTES-0.3.7.md` must describe: administrator authentication/privacy hardening, Argon2id password storage, server-side sessions, first-run admin setup, API-key compatibility, security headers, docs/OpenAPI protection, downloader CPU-aware responsiveness fix, and release/CI hardening.

- [ ] **Step 5: Run full tests**

Run: `python -m pytest -q` and `python -m compileall -q scarletx tests`.
Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `Prepare ScarletX 0.3.7 release`.

---

### Task 4: Validate, merge, tag, publish, and update TrueNAS submission

**Files/repos:**
- ScarletX PR from `release-ci-hardening` to `main`.
- Git tag `v0.3.7` on the merged main commit.
- GitHub Release `v0.3.7` using `RELEASE-NOTES-0.3.7.md`.
- `terralayer/apps` branch `scarletx-community-app` / upstream TrueNAS PR #5698.

- [ ] **Step 1: Open the ScarletX PR and require green CI**

Verify Python 3.11/3.12/3.13 tests and TrueNAS render validation on the PR.

- [ ] **Step 2: Merge only after current-head verification**

Use the exact verified head SHA.

- [ ] **Step 3: Verify main workflows**

Require `Tests`, `Container`, and `TrueNAS App Validation` to complete successfully for the merged main commit where applicable.

- [ ] **Step 4: Create `v0.3.7` tag**

Tag the verified merged main commit, not a feature-branch SHA.

- [ ] **Step 5: Verify immutable release image**

Require the tag-triggered Container workflow to complete successfully and publish `ghcr.io/terralayer/scarletx:0.3.7`.

- [ ] **Step 6: Create GitHub Release**

Release title: `ScarletX 0.3.7`; body comes from `RELEASE-NOTES-0.3.7.md`.

- [ ] **Step 7: Update TrueNAS fork submission**

Copy the six current source-definition files from `packaging/truenas/scarletx/` into `terralayer/apps:scarletx-community-app` so upstream PR #5698 references `0.3.7` / catalog `1.0.1`.

- [ ] **Step 8: Verify upstream PR #5698 state**

Confirm source files, mergeability, comments/reviews, and CI/action-required state without guessing.

---

## Self-review

Coverage: immutable image tagging, 0.3.7 metadata consistency, TrueNAS app/catalog bump, application-code validation triggers, Node-24 action cleanup, full test matrix, release tag/release, and upstream TrueNAS synchronization are all assigned to explicit tasks. No placeholders or deferred implementation steps remain.