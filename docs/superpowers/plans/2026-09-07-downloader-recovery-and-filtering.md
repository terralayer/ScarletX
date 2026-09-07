# Downloader Recovery and Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the built-in downloader recoverable, reject undersized/sample/image releases, isolate completed-import failures, simplify Library media details, and make UI authentication opt-in.

**Architecture:** Add focused release-policy and downloader-supervisor units, then wire them through the existing FastAPI routes and static frontend. Preserve the current two-container web/backend deployment and SQLite data model; authentication remains session-based when enabled but defaults off.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, asyncio, pytest, vanilla JavaScript, Nginx/Docker.

**Spec:** `docs/superpowers/specs/2026-09-07-downloader-recovery-and-filtering-design.md`

## Global Constraints

- The minimum whole-release size is exactly 524,288,000 bytes (500 MiB).
- UI authentication defaults disabled on fresh installs and upgrades.
- Restart affects only the native downloader worker and preserves partial downloads.
- Existing backend media response fields remain API-compatible.
- Every production behavior change starts with a failing test.

---

### Task 1: Opt-in UI authentication backend

**Files:**
- Modify: `scarletx/config.py`
- Modify: `scarletx/settings_store.py`
- Modify: `scarletx/schemas.py`
- Modify: `scarletx/http_security.py`
- Modify: `scarletx/auth_routes.py`
- Modify: `scarletx/routes/application.py`
- Test: `tests/test_auth_middleware.py`
- Test: `tests/test_auth_routes.py`

**Interfaces:**
- Produces: `Settings.ui_auth_enabled: bool`
- Produces: `PATCH /api/auth/admin` accepting `AdminCredentialsWrite` while auth is disabled and returning a signed-in session.
- Produces: `PATCH /api/settings/security` accepting `ui_auth_enabled`, credentials when enabling, and existing API-key fields.
- Produces: `/api/auth/status` field `enabled: bool`.

- [ ] **Step 1: Write failing settings and middleware tests**

```python
def test_private_api_is_open_when_ui_auth_is_disabled():
    client, _ = make_app(ui_auth_enabled=False)
    assert client.get("/api/private").status_code == 200

def test_private_api_requires_session_when_ui_auth_is_enabled():
    client, _ = make_app(ui_auth_enabled=True)
    assert client.get("/api/private").status_code == 401
```

Add route tests proving status reports `enabled=False`, credentials can be
created while disabled, enabling creates a session, and disabling retains the
administrator record.

- [ ] **Step 2: Run the focused tests and verify the expected failures**

Run: `python -m pytest tests/test_auth_middleware.py tests/test_auth_routes.py -q`
Expected: failures for the missing `ui_auth_enabled` setting and status/transition behavior.

- [ ] **Step 3: Implement the persisted setting and auth bypass**

Add `ui_auth_enabled: bool = False` to `Settings`, seed/load it through
`settings_store`, and have `install_authentication` call the downstream app
without session checks when false. Extend auth status and security serialization.
Enabling must validate username/password, upsert the sole administrator, create
the current session cookie, then persist the setting. Disabling requires the
current session when the setting was enabled, sets the flag false, and revokes
sessions without deleting the account.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_auth_middleware.py tests/test_auth_routes.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/config.py scarletx/settings_store.py scarletx/schemas.py scarletx/http_security.py scarletx/auth_routes.py scarletx/routes/application.py tests/test_auth_middleware.py tests/test_auth_routes.py
git commit -m "feat: make UI authentication opt-in"
```

### Task 2: Opt-in authentication frontend

**Files:**
- Modify: `frontend/auth.js`
- Modify: `frontend/app.js`
- Modify: `tests/test_auth_ui.py`
- Modify: `tests/test_module_boundaries.py`

**Interfaces:**
- Consumes: `/api/auth/status.enabled` and `PATCH /api/settings/security`.
- Produces: immediate app boot when auth is disabled and Security settings controls for enabling/disabling it.

- [ ] **Step 1: Write failing frontend contract tests**

```python
def test_auth_gate_boots_immediately_when_ui_auth_is_disabled():
    script = text("frontend/auth.js")
    assert "if (!status.enabled)" in script
    assert "showOpenApp(status)" in script

def test_security_settings_can_enable_ui_auth():
    script = text("frontend/app.js")
    assert "ui_auth_enabled" in script
    assert "securityUsername" in script
    assert "securityPasswordConfirm" in script
```

Also assert that token-based first-run setup fields and `/api/setup/admin` are
not part of normal frontend boot.

- [ ] **Step 2: Run tests and verify they fail for missing opt-in behavior**

Run: `python -m pytest tests/test_auth_ui.py tests/test_module_boundaries.py -q`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Implement frontend bypass and settings controls**

Update `auth.js` so disabled status hides the account/gate, starts the event
stream, and boots the app immediately. Retain only the login path for enabled
auth. Add Security form fields and submit logic in `app.js`; credentials are
required only when turning authentication on. Reload after a successful auth
state transition.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_auth_ui.py tests/test_module_boundaries.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/auth.js frontend/app.js tests/test_auth_ui.py tests/test_module_boundaries.py
git commit -m "feat: expose optional UI authentication settings"
```

### Task 3: Whole-release and payload filtering

**Files:**
- Create: `scarletx/release_policy.py`
- Modify: `scarletx/automation.py`
- Modify: `scarletx/usenet/worker.py`
- Modify: `scarletx/library_management.py`
- Test: `tests/test_release_policy.py`
- Test: `tests/test_download_pipeline.py`

**Interfaces:**
- Produces: `MIN_RELEASE_BYTES = 524_288_000`.
- Produces: `release_rejection_reason(title: str, size: int | None) -> str | None`.
- Produces: `nzb_file_is_ignored(item: NZBFile, index: int) -> bool`.

- [ ] **Step 1: Write failing policy tests**

```python
def test_rejects_release_below_500_mib():
    assert release_rejection_reason("Studio Scene 1080p", MIN_RELEASE_BYTES - 1)

def test_accepts_release_at_boundary_and_unknown_size():
    assert release_rejection_reason("Studio Scene 1080p", MIN_RELEASE_BYTES) is None
    assert release_rejection_reason("Studio Scene 1080p", None) is None

@pytest.mark.parametrize("title", ["Scene SAMPLE", "Scene image set", "Scene screenshots"])
def test_rejects_sample_and_image_titles(title):
    assert release_rejection_reason(title, MIN_RELEASE_BYTES)
```

Add NZB tests proving image/sample entries are excluded, archives remain, total
advertised NZB size below the threshold fails before fetching, and a payload
containing only samples fails rather than importing the sample.

- [ ] **Step 2: Run focused tests and verify expected failures**

Run: `python -m pytest tests/test_release_policy.py tests/test_download_pipeline.py -q`
Expected: FAIL because the policy module and filtering behavior do not exist.

- [ ] **Step 3: Implement release policy and downloader enforcement**

Use standalone alphanumeric tokens for sample/image title matching. Apply the
helper in both `choose_best_release` and `grab_specific_release`. After
`parse_nzb`, reject the whole advertised NZB when below the constant. Exclude
image and sample/trailer NZB entries from file state construction; raise a clear
policy error if none remain. Change primary video selection to raise when every
candidate is a sample/trailer instead of falling back.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_release_policy.py tests/test_download_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/release_policy.py scarletx/automation.py scarletx/usenet/worker.py scarletx/library_management.py tests/test_release_policy.py tests/test_download_pipeline.py
git commit -m "feat: reject small sample and image releases"
```

### Task 4: Supervised downloader lifecycle and restart API

**Files:**
- Create: `scarletx/downloader_supervisor.py`
- Modify: `scarletx/routes/application.py`
- Modify: `tests/fixtures/route_contract_0310.json`
- Create: `tests/test_downloader_supervisor.py`
- Modify: `tests/test_module_boundaries.py`

**Interfaces:**
- Produces: `DownloaderSupervisor.start()`, `restart()`, `stop()`, and `status()`.
- Produces: `POST /api/download-client/restart`.
- Extends: `GET /api/download-client/status` with `worker` status.

- [ ] **Step 1: Write failing supervisor tests**

```python
@pytest.mark.asyncio
async def test_restart_cancels_worker_requeues_interrupted_jobs_and_preserves_paused(tmp_path):
    supervisor = DownloaderSupervisor(Session, settings_loader, worker=fake_worker)
    await supervisor.start()
    result = await supervisor.restart()
    assert result["state"] == "running"
    assert result["requeued"] == 1

@pytest.mark.asyncio
async def test_unexpected_exit_is_replaced_after_bounded_delay():
    supervisor = DownloaderSupervisor(Session, settings_loader, worker=crash_once, restart_delay=0)
    await supervisor.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert supervisor.status()["alive"] is True
```

Add route-contract checks for the restart endpoint and worker status object.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `python -m pytest tests/test_downloader_supervisor.py tests/test_module_boundaries.py -q`
Expected: FAIL because the supervisor is missing.

- [ ] **Step 3: Implement the supervisor and lifecycle wiring**

Keep a single supervisor instance in `application.py`. Replace the anonymous
native worker watcher with `await supervisor.start()` and stop it in lifespan
shutdown. The supervisor requeues only `downloading` and `postprocessing`, clears
persisted speed/ETA, serializes restart calls with an asyncio lock, supervises
unexpected exits with bounded delay, and never creates two active worker tasks.

- [ ] **Step 4: Add and verify routes**

Return `{"worker": supervisor.status(), ...}` from status. Restart returns the
supervisor result and maps only unavailable/shutdown conditions to HTTP 503.
Update the frozen route fixture.

Run: `python -m pytest tests/test_downloader_supervisor.py tests/test_module_boundaries.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/downloader_supervisor.py scarletx/routes/application.py tests/test_downloader_supervisor.py tests/test_module_boundaries.py tests/fixtures/route_contract_0310.json
git commit -m "feat: supervise and restart the native downloader"
```

### Task 5: Completed-import fault isolation

**Files:**
- Modify: `scarletx/download_processing.py`
- Modify: `tests/test_download_pipeline.py`

**Interfaces:**
- Preserves: `process_completed_downloads(...) -> dict`.
- Changes: `failed` counts both terminal download failures and retryable per-job import failures.

- [ ] **Step 1: Write failing per-job isolation tests**

Build two completed tracked jobs. Make the first importer raise `OSError("disk
offline")` and allow the second to import. Assert the function returns normally,
the first remains `import_pending` with the bounded error, and processing reaches
the second. Add a webhook emitter failure test proving durable import still
returns normally.

- [ ] **Step 2: Run and verify failures**

Run: `python -m pytest tests/test_download_pipeline.py -q`
Expected: FAIL because unexpected job and webhook errors escape.

- [ ] **Step 3: Isolate operational failures**

Catch ordinary `Exception` at each completed-job boundary without catching
`CancelledError`/`BaseException`. Persist `import_pending`, error, and timestamp,
emit failed status, increment `failed`, then continue. Wrap each webhook delivery
so notification transport cannot roll back or mask durable job results.

- [ ] **Step 4: Run and verify passing tests**

Run: `python -m pytest tests/test_download_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/download_processing.py tests/test_download_pipeline.py
git commit -m "fix: isolate completed download processing failures"
```

### Task 6: Activity restart control and simplified Library UI

**Files:**
- Modify: `frontend/app.js`
- Modify: `tests/test_ui_theme.py`
- Modify: `tests/test_auth_ui.py`

**Interfaces:**
- Consumes: `POST /api/download-client/restart`.
- Changes: Activity header controls and Library table/player presentation.

- [ ] **Step 1: Write failing UI source-contract tests**

Assert `frontend/app.js` includes `id="restartDownloader"`, posts to the restart
endpoint, and renders restart feedback. Assert the media-table template has no
`<th>File</th>`, no `x.filename`, and no `x.audio_codec`, while missing state is
still present. Assert player facts contain no `<b>Audio</b>`.

- [ ] **Step 2: Run and verify expected failures**

Run: `python -m pytest tests/test_ui_theme.py tests/test_auth_ui.py -q`
Expected: FAIL on restart and simplified Library assertions.

- [ ] **Step 3: Implement the Activity and Library changes**

Add the confirmed restart button handler and queue refresh. Remove the File
column, move Missing under the scene/studio cell, remove audio codec from media
rows, and remove the player Audio fact. Do not remove backend response fields.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `python -m pytest tests/test_ui_theme.py tests/test_auth_ui.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js tests/test_ui_theme.py tests/test_auth_ui.py
git commit -m "feat: add downloader restart and simplify library media UI"
```

### Task 7: Full verification

**Files:**
- Modify only if a verified regression requires a scoped correction.

- [ ] **Step 1: Run formatting and static checks**

Run: `python -m ruff check scarletx tests`
Expected: PASS.

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Validate package and container contracts**

Run: `python -m compileall -q scarletx`
Run: `docker compose config --quiet`
Expected: both commands exit 0.

- [ ] **Step 4: Inspect final diff and repository state**

Run: `git diff --check HEAD~6..HEAD`
Run: `git status --short --branch`
Expected: no whitespace errors and a clean working tree ahead of `origin/main`.
