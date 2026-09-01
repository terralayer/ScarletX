# ScarletX Status Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full ASCII/ANSI startup health dashboard and safe structured live status events while keeping version 0.3.9 unchanged on an isolated feature branch.

**Architecture:** Add `scarletx/status_console.py` as the single console presentation/status boundary. It collects a best-effort read-only startup snapshot from the current SQLAlchemy session and Settings, renders grouped status rows, and exposes `emit_status()` for workers. `scarletx/main.py` prints the snapshot after bootstrap and then starts workers as before.

**Tech Stack:** Python 3.11+, SQLAlchemy 2, FastAPI lifespan, ANSI terminal escapes, pytest.

**Spec:** `docs/superpowers/specs/2026-09-01-status-console-design.md`

## Global Constraints

- Work only on `feature/status-console`; do not merge to `main`.
- Keep `pyproject.toml` version at `0.3.9` and FastAPI version at `0.3.9`.
- Startup status collection performs no new external network requests.
- Never log API keys, passwords, setup tokens, secret-key contents, or credential-bearing URLs.
- Status collection failures are non-fatal.

---

### Task 1: Console renderer and sanitization

**Files:**
- Create: `tests/test_status_console.py`
- Create: `scarletx/status_console.py`

**Interfaces:**
- Produces: `StatusRow`, `StatusGroup`, `render_dashboard(...)`, `emit_status(...)`, `sanitize_console_text(...)`.

- [ ] Write failing tests for required ASCII wordmark/groups, ANSI enable/disable, severity symbols, alignment, and control-character sanitization.
- [ ] Run CI via a draft PR and confirm the tests fail because `scarletx.status_console` does not exist.
- [ ] Implement the renderer and emitter with no database dependencies.
- [ ] Re-run CI and confirm renderer tests pass.

### Task 2: Real startup snapshot

**Files:**
- Modify: `tests/test_status_console.py`
- Modify: `scarletx/status_console.py`

**Interfaces:**
- Produces: `collect_startup_status(db, settings) -> list[StatusGroup]`.

- [ ] Add failing tests using an in-memory SQLAlchemy session/settings fixture for subsystem groups, counts, path/tool degradation, redaction, and no network probes.
- [ ] Implement best-effort collectors for SYSTEM, METADATA, SEARCH, USENET, POST-PROCESSING, LIBRARY, STORAGE, and SECURITY.
- [ ] Verify all collector tests pass.

### Task 3: Lifespan integration

**Files:**
- Modify: `tests/test_status_console.py`
- Modify: `scarletx/main.py`

**Interfaces:**
- Consumes: `collect_startup_status`, `render_dashboard`, `emit_status`.

- [ ] Add a failing source/integration test asserting lifespan invokes the status dashboard after settings are loaded and the FastAPI version remains 0.3.9.
- [ ] Integrate dashboard printing into lifespan without changing worker ordering or version metadata.
- [ ] Emit lifecycle ACTIVE/READY/STOPPED events around background worker startup/shutdown.
- [ ] Verify integration tests pass.

### Task 4: High-value live worker events

**Files:**
- Modify: `scarletx/native_usenet.py`
- Modify: `scarletx/download_processing.py`
- Modify: `scarletx/backups.py`
- Modify: `scarletx/media_library.py`
- Modify: `tests/test_status_console.py`

**Interfaces:**
- Consumes: `emit_status(component, state, detail="", severity=None)`.

- [ ] Add failing source/behavior tests requiring native Usenet provider connect/retry/failure, download/post-processing transitions, imports, backups, and library scans to emit structured status lines.
- [ ] Wire `emit_status()` only at existing state-transition/error boundaries; do not alter operational behavior.
- [ ] Ensure sensitive exception text is sanitized before output.
- [ ] Verify worker tests pass.

### Task 5: Full verification

**Files:**
- Verify: `pyproject.toml`, `scarletx/main.py`, all tests.

- [ ] Confirm `version = "0.3.9"` and FastAPI `version="0.3.9"` remain unchanged.
- [ ] Run the complete pytest matrix, compileall, dependency audit, and both container builds through the draft PR CI.
- [ ] Review the branch diff for secret leakage, accidental network probes, unrelated changes, or version bumping.
- [ ] Leave the PR draft/unmerged and report the branch/CI status.
