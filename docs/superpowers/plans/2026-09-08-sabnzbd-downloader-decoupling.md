# ScarletX SABnzbd Downloader Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SABnzbd the sole active downloader while preserving ScarletX search/monitor/import ownership and retaining native-downloader code/data as dormant compatibility state.

**Architecture:** Keep `scarletx/download_clients.py` as the application-facing facade, add a focused SABnzbd adapter that translates SAB queue/history into neutral ScarletX download state, reuse `TrackedDownload` + `TrackedDownloadMeta` for persistence, and rewrite completed-download reconciliation to query the downloader facade rather than `NativeUsenetJob`. Remove the native worker/settings/queue from normal runtime/UI without deleting its source or tables.

**Tech Stack:** Python 3.11+, FastAPI, httpx, SQLAlchemy 2, Pydantic, vanilla JS frontend, Docker/TrueNAS packaging, pytest/pytest-asyncio/Ruff.

**Spec:** `docs/superpowers/specs/2026-09-07-sabnzbd-downloader-decoupling-design.md`

## Global Constraints

- Base implementation work on the latest `main`, not the older design-branch snapshot.
- SABnzbd is the only active downloader in this iteration; do not add a runtime client selector.
- SABnzbd owns NNTP, download retry, PAR repair, archive extraction, and speed limiting.
- ScarletX owns search, monitoring, RSS/manual grabs, tracking, completion reconciliation, import, naming, library updates, and post-import indexing.
- Preserve `scarletx/native_usenet.py`, `scarletx/usenet/`, `NativeUsenetJob`, and existing native database rows/settings as dormant compatibility state.
- Do not migrate in-progress native jobs into SABnzbd.
- Do not automatically delete SAB history after import.
- `sabnzbd_api_key` must use the existing encrypted settings store and must never be returned in plaintext or written to logs.
- Use bounded HTTP timeouts. A SAB outage must not crash ScarletX or mark active downloads failed merely because polling failed.
- Reuse `download_poll_seconds` for baseline reconciliation cadence.
- Shared completed-download paths between SABnzbd and ScarletX must be identical for the first implementation; no remote path mapper is introduced.
- Every behavior change follows RED -> GREEN tests, then focused/full verification.

---

### Task 1: Lock the current-main baseline and downloader contracts

**Files:**
- Create: `tests/test_sabnzbd_downloader.py`
- Modify: `tests/test_module_boundaries.py`

**Interfaces:**
- Consumes: current `main` public downloader facade, settings store, application startup, activity routes.
- Produces: regression contracts that require SAB-neutral product behavior while preserving dormant native imports.

- [ ] **Step 1: Add source-boundary RED tests**

Add tests that assert:

```python
def test_active_download_facade_does_not_import_native_usenet():
    source = (ROOT / "scarletx" / "download_clients.py").read_text(encoding="utf-8")
    assert "native_usenet" not in source
    assert "enqueue_url" not in source


def test_native_downloader_remains_importable_for_compatibility():
    from scarletx import native_usenet
    from scarletx.usenet import worker
    assert native_usenet
    assert worker


def test_normal_startup_does_not_start_native_worker():
    source = (ROOT / "scarletx" / "routes" / "application.py").read_text(encoding="utf-8")
    assert "asyncio.create_task(native_worker_loop" not in source
```

- [ ] **Step 2: Run RED boundary tests**

Run:

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_module_boundaries.py -q
```

Expected: new active-boundary assertions fail on current native wiring while dormant-native import assertion passes.

- [ ] **Step 3: Commit the RED characterization**

```bash
git add tests/test_sabnzbd_downloader.py tests/test_module_boundaries.py
git commit -m "test: define SABnzbd downloader boundary"
```

---

### Task 2: Add SAB settings without destroying legacy native settings

**Files:**
- Modify: `scarletx/config.py`
- Modify: `scarletx/settings_store.py`
- Modify: `scarletx/schemas.py`
- Test: `tests/test_sabnzbd_downloader.py`
- Test: `tests/test_hardening_039.py`

**Interfaces:**
- Produces: `Settings.sabnzbd_url: str`, `Settings.sabnzbd_api_key: SecretStr`, `Settings.sabnzbd_category: str`, `Settings.sabnzbd_priority: int`; `SabnzbdSettingsWrite`.

- [ ] **Step 1: Add RED settings tests**

```python
def test_sab_settings_defaults():
    settings = Settings()
    assert settings.sabnzbd_url == ""
    assert settings.sabnzbd_api_key.get_secret_value() == ""
    assert settings.sabnzbd_category == "scarletx"
    assert settings.sabnzbd_priority == 0


def test_sab_api_key_is_encrypted_at_rest(db_session):
    set_setting(db_session, "sabnzbd_api_key", "secret-key")
    row = db_session.get(AppSetting, "sabnzbd_api_key")
    assert row.is_secret is True
    assert "secret-key" not in row.value
    assert load_database_settings(db_session).sabnzbd_api_key.get_secret_value() == "secret-key"


def test_seed_preserves_legacy_native_settings_and_sab_settings(db_session):
    set_setting(db_session, "native_usenet_enabled", "true")
    set_setting(db_session, "sabnzbd_url", "http://sab:8080")
    seed_database_settings(db_session)
    assert db_session.get(AppSetting, "native_usenet_enabled") is not None
    assert db_session.get(AppSetting, "sabnzbd_url").value == "http://sab:8080"
```

- [ ] **Step 2: Run RED settings tests**

Run:

```bash
pytest tests/test_sabnzbd_downloader.py -q -k 'sab_settings or api_key or seed_preserves'
```

Expected: fail because SAB fields are not active settings and current legacy cleanup removes SAB keys.

- [ ] **Step 3: Implement settings fields**

Add to `Settings`:

```python
sabnzbd_url: str = os.getenv("SCARLETX_SABNZBD_URL", "").strip().rstrip("/")
sabnzbd_api_key: SecretStr = SecretStr(os.getenv("SCARLETX_SABNZBD_API_KEY", ""))
sabnzbd_category: str = os.getenv("SCARLETX_SABNZBD_CATEGORY", "scarletx")
sabnzbd_priority: int = int(os.getenv("SCARLETX_SABNZBD_PRIORITY", "0"))
```

Add `sabnzbd_api_key` to `SECRET_KEYS`, remove the SAB keys from destructive `LEGACY_KEYS`, add SAB defaults to `default_setting_values()`, and leave native keys intact but no longer product-facing.

Add:

```python
class SabnzbdSettingsWrite(BaseModel):
    url: str = ""
    api_key: str | None = None
    category: str = Field(default="scarletx", max_length=100)
    priority: int = Field(default=0, ge=-100, le=100)
```

- [ ] **Step 4: Run GREEN settings tests**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_hardening_039.py -q
```

- [ ] **Step 5: Commit**

```bash
git add scarletx/config.py scarletx/settings_store.py scarletx/schemas.py tests/test_sabnzbd_downloader.py tests/test_hardening_039.py
git commit -m "feat: add persistent SABnzbd settings"
```

---

### Task 3: Implement the neutral downloader models and SABnzbd adapter

**Files:**
- Create: `scarletx/downloaders/__init__.py`
- Create: `scarletx/downloaders/sabnzbd.py`
- Replace: `scarletx/download_clients.py`
- Test: `tests/test_sabnzbd_downloader.py`

**Interfaces:**
- Produces:
  - `SubmittedDownload(client: str, ids: tuple[str, ...])`
  - `DownloadStatus(external_id, client, name, state, progress, total_bytes, downloaded_bytes, speed_bps, eta_seconds, completed_path, error)`
  - `ClientHealth(ok: bool, configured: bool, message: str)`
  - `async test_connection(settings) -> ClientHealth`
  - `async submit_release(settings, release, *, session_factory=None, name=None, category=None) -> SubmittedDownload`
  - `async get_downloads(settings, external_ids: Sequence[str]) -> dict[str, DownloadStatus]`

- [ ] **Step 1: Add RED adapter tests with `httpx.MockTransport`**

Cover:

```python
@pytest.mark.asyncio
async def test_sab_test_connection_uses_version_endpoint_and_api_key(): ...

@pytest.mark.asyncio
async def test_sab_submit_propagates_url_name_category_priority_and_returns_nzo_id(): ...

@pytest.mark.asyncio
async def test_sab_status_merges_queue_and_history(): ...

@pytest.mark.asyncio
async def test_sab_history_failure_maps_to_failed(): ...

@pytest.mark.asyncio
async def test_sab_missing_from_queue_but_present_in_history_is_completed(): ...

@pytest.mark.asyncio
async def test_sab_absent_from_queue_and_history_is_unknown(): ...

@pytest.mark.asyncio
async def test_sab_network_error_raises_sanitized_download_client_error(): ...
```

Mock SAB JSON shape using the standard API envelope (`queue.slots`, `history.slots`, `status`, `nzo_id`, `storage`, byte/MB progress fields).

- [ ] **Step 2: Run RED adapter tests**

```bash
pytest tests/test_sabnzbd_downloader.py -q -k 'connection or submit or status or history or network'
```

- [ ] **Step 3: Implement `SabnzbdClient`**

Use `httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))`. Build all requests from sanitized base URL plus query params. Never interpolate the API key into exception messages.

Required methods:

```python
class SabnzbdClient:
    name = "sabnzbd"

    async def test_connection(self) -> ClientHealth: ...
    async def submit_release(self, release, *, name=None, category=None) -> SubmittedDownload: ...
    async def get_downloads(self, external_ids) -> dict[str, DownloadStatus]: ...
```

Use `mode=addurl` for Newznab download URLs, `mode=queue&output=json` for active state, and `mode=history&output=json&limit=...` for terminal state. Query queue/history once per reconciliation batch, not once per tracked download.

- [ ] **Step 4: Replace the facade**

`scarletx/download_clients.py` must import only neutral/SAB modules and expose stable functions. `resolve_client(settings)` returns `"sabnzbd"`; `client_ready(settings)` checks non-empty URL + API key, not network reachability.

- [ ] **Step 5: Run GREEN adapter tests**

```bash
pytest tests/test_sabnzbd_downloader.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scarletx/downloaders scarletx/download_clients.py tests/test_sabnzbd_downloader.py
git commit -m "feat: add SABnzbd download client"
```

---

### Task 4: Route all grab paths through SAB and label them correctly

**Files:**
- Modify: `scarletx/automation.py`
- Modify: `scarletx/rss.py` only if it bypasses `grab_specific_release`
- Modify: `scarletx/routes/application.py` for manual grab path only where needed
- Test: `tests/test_sabnzbd_downloader.py`

**Interfaces:**
- Consumes: `submit_release()` from Task 3.
- Produces: every manual/monitor/automatic/RSS grab persists `TrackedDownloadMeta.download_client == "sabnzbd"` and history/UI copy says SABnzbd.

- [ ] **Step 1: Add RED grab tests**

Test a representative `grab_specific_release()` with a monkeypatched facade:

```python
async def fake_submit(*_args, **_kwargs):
    return SubmittedDownload(client="sabnzbd", ids=("SAB-123",))
```

Assert `TrackedDownload.nzo_id == "SAB-123"`, metadata client `sabnzbd`, and History contains `SABnzbd`, not `ScarletX Built-In`.

Add source contract asserting no active application grab code imports `native_usenet`.

- [ ] **Step 2: Run RED tests**

```bash
pytest tests/test_sabnzbd_downloader.py -q -k grab
```

- [ ] **Step 3: Change labels/wiring minimally**

Keep `_track()` and `TrackedDownload.nzo_id` for schema compatibility; treat `nzo_id` as the persisted external downloader ID. Replace hard-coded native product labels with `SABnzbd` or `submitted.client` mapping.

- [ ] **Step 4: Run GREEN tests**

```bash
pytest tests/test_sabnzbd_downloader.py -q -k grab
```

- [ ] **Step 5: Commit**

```bash
git add scarletx/automation.py scarletx/rss.py scarletx/routes/application.py tests/test_sabnzbd_downloader.py
git commit -m "refactor: route grabs through SABnzbd"
```

---

### Task 5: Reconcile SAB queue/history and hand completions to the existing import pipeline

**Files:**
- Modify: `scarletx/download_processing.py`
- Test: `tests/test_sabnzbd_downloader.py`
- Modify: `tests/test_download_pipeline.py`
- Modify: current import-retry tests from PR #48 if necessary

**Interfaces:**
- Consumes: `get_downloads(settings, external_ids)` from Task 3.
- Produces: native-independent `process_completed_downloads()` that preserves bounded import retries and exactly-once imported state.

- [ ] **Step 1: Add RED reconciliation tests**

Cover:

```python
@pytest.mark.asyncio
async def test_sab_downloading_updates_tracked_state_without_import(...): ...

@pytest.mark.asyncio
async def test_sab_completed_storage_path_enters_import_once(...): ...

@pytest.mark.asyncio
async def test_repeated_completed_poll_does_not_duplicate_import(...): ...

@pytest.mark.asyncio
async def test_sab_failed_job_is_blocklisted_and_never_imported(...): ...

@pytest.mark.asyncio
async def test_sab_poll_outage_preserves_last_known_state(...): ...

@pytest.mark.asyncio
async def test_restart_reconciliation_uses_persisted_external_id(...): ...
```

- [ ] **Step 2: Run RED reconciliation tests**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_download_pipeline.py -q
```

- [ ] **Step 3: Remove active `NativeUsenetJob` state dependency**

Replace `_pending_state_maps()` with a neutral metadata/client grouping helper. Batch the external IDs for rows whose `TrackedDownloadMeta.download_client == "sabnzbd"`, call `get_downloads()` once, and translate returned `DownloadStatus` objects to tracked fields.

- [ ] **Step 4: Preserve PR #48 retry semantics**

Do not regress current 3-attempt import retry/backoff behavior. SAB completed jobs remain `import_pending` during cooldown and become terminal `import_failed` after the existing maximum attempt policy.

- [ ] **Step 5: Remove native-only completion cleanup from SAB path**

Do not mutate `NativeUsenetJob.output_path` and do not delete SAB completed payload directories from ScarletX. Import mode controls media handling; SAB history/payload ownership remains external.

- [ ] **Step 6: Run GREEN reconciliation tests**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_download_pipeline.py -q
```

- [ ] **Step 7: Commit**

```bash
git add scarletx/download_processing.py tests/test_sabnzbd_downloader.py tests/test_download_pipeline.py
git commit -m "refactor: reconcile completed downloads through SABnzbd"
```

---

### Task 6: Replace native downloader settings/status routes with SAB routes

**Files:**
- Modify: `scarletx/routes/application.py`
- Modify: `scarletx/schemas.py`
- Modify: `tests/fixtures/route_contract_0310.json` only for intentional route changes
- Test: `tests/test_sabnzbd_downloader.py`
- Test: `tests/test_module_boundaries.py`

**Interfaces:**
- Produces:
  - `PATCH /api/settings/sabnzbd`
  - `GET /api/download-client/status`
  - `POST /api/download-client/test`

- [ ] **Step 1: Add RED API tests**

Assert `/api/settings` exposes:

```json
{
  "sabnzbd": {
    "url": "http://sab:8080",
    "api_key_configured": true,
    "category": "scarletx",
    "priority": 0
  }
}
```

and does not expose native provider passwords/settings as active product configuration.

Test that patching with an empty `api_key` preserves the current stored secret; test connection delegates to the SAB adapter and maps adapter errors to 502 without secrets.

- [ ] **Step 2: Run RED API tests**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_module_boundaries.py -q -k 'settings or download_client'
```

- [ ] **Step 3: Implement SAB routes and retire active native routes**

Remove active `/api/settings/native-usenet` and native-provider test routes from the normal route contract. Keep dormant Python compatibility functions only if tests/plugins require importability; they should not be reachable from the product UI/API.

- [ ] **Step 4: Update route fixture intentionally**

Regenerate `tests/fixtures/route_contract_0310.json` from the current app route set after verifying only the intended native->SAB route changes occur.

- [ ] **Step 5: Run GREEN API/contract tests**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_module_boundaries.py -q
```

- [ ] **Step 6: Commit**

```bash
git add scarletx/routes/application.py scarletx/schemas.py tests/test_sabnzbd_downloader.py tests/test_module_boundaries.py tests/fixtures/route_contract_0310.json
git commit -m "feat: expose SABnzbd downloader settings and health"
```

---

### Task 7: Stop the native worker and make status/health SAB-aware

**Files:**
- Modify: `scarletx/routes/application.py`
- Modify: `scarletx/status_console.py`
- Test: `tests/test_sabnzbd_downloader.py`
- Modify: `tests/test_status_console.py`

**Interfaces:**
- Produces: startup worker list without `native_worker_loop`; startup/status console shows SAB configuration/reachability category without exposing secrets.

- [ ] **Step 1: Add RED startup/status tests**

Assert native worker is absent from lifecycle task construction, background worker count adjusts, and status snapshot no longer requires native provider state for healthy ScarletX startup.

- [ ] **Step 2: Run RED tests**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_status_console.py -q
```

- [ ] **Step 3: Disconnect native worker**

Delete the runtime `asyncio.create_task(native_worker_loop(...))` entry and remove native imports that exist solely for startup/status. Do not delete native modules.

- [ ] **Step 4: Add SAB status group**

Startup snapshot is no-network; report `Configured` or `Not configured` from settings. Runtime `/api/download-client/status` performs network health when requested.

- [ ] **Step 5: Run GREEN tests and commit**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_status_console.py -q
git add scarletx/routes/application.py scarletx/status_console.py tests/test_sabnzbd_downloader.py tests/test_status_console.py
git commit -m "refactor: shelve native downloader runtime"
```

---

### Task 8: Convert Activity/Downloads UI from native control surface to ScarletX tracking surface

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css` only if required
- Modify: backend activity serialization in `scarletx/routes/application.py`
- Test: `tests/test_sabnzbd_downloader.py`
- Test: UI/source-contract tests affected by PRs #49-#52 and #57

**Interfaces:**
- Produces: current 50-row Activity pagination and true-count behavior remain; rows display normalized state/progress/size and SABnzbd client indicator; native pause/resume/cancel controls are removed for this iteration.

- [ ] **Step 1: Add RED UI contracts**

Assert frontend source contains `SABnzbd`, does not contain `data-native-act`, and does not render native provider/connection-cap fields as downloader controls. Assert pagination remains 50 and the true active count remains independent of snapshot cap.

- [ ] **Step 2: Run RED UI tests**

```bash
pytest tests -q -k 'activity or queue or frontend or sabnzbd'
```

- [ ] **Step 3: Normalize backend activity rows**

Return neutral fields only: external ID, client, state/client status, progress, total/downloaded bytes, speed/ETA when SAB reports them, scene/release identity, error, storage/import state. Do not fetch or serialize `NativeUsenetJob` for new SAB rows.

- [ ] **Step 4: Simplify Activity controls**

Keep the current pagination/layout improvements. Remove native pause/resume/cancel/reprocess buttons; advanced queue administration stays in SABnzbd. Preserve failed/import status visibility.

- [ ] **Step 5: Run GREEN UI tests and commit**

```bash
pytest tests -q -k 'activity or queue or frontend or sabnzbd'
git add frontend/app.js frontend/styles.css scarletx/routes/application.py tests
git commit -m "ui: show SABnzbd-backed download activity"
```

---

### Task 9: Replace Settings UI native provider controls with SABnzbd configuration

**Files:**
- Modify: `frontend/app.js`
- Modify: `frontend/styles.css` only if necessary
- Test: frontend/settings tests

**Interfaces:**
- Consumes: Task 6 settings endpoints.
- Produces: URL, API key, category, priority, Test Connection UI.

- [ ] **Step 1: Add RED frontend assertions**

Require labels/fields `SABnzbd URL`, `API Key`, `Category`, `Priority`, `Test Connection`; forbid normal-settings labels for native NNTP provider host/port/connections, repair, unpack, and native speed cap.

- [ ] **Step 2: Run RED tests**

```bash
pytest tests -q -k 'settings and frontend'
```

- [ ] **Step 3: Implement SAB Settings panel**

Use masked API-key semantics: blank submitted key preserves existing secret. Connection test calls `/api/download-client/test`; saving calls `/api/settings/sabnzbd`.

- [ ] **Step 4: Run GREEN tests and commit**

```bash
pytest tests -q -k 'settings or frontend'
git add frontend/app.js frontend/styles.css tests
git commit -m "ui: configure SABnzbd as the downloader"
```

---

### Task 10: Upgrade safety for current databases and legacy native jobs

**Files:**
- Modify: `scarletx/routes/application.py` migration only where necessary
- Modify: `scarletx/settings_store.py`
- Test: `tests/test_sabnzbd_downloader.py`
- Test: existing migration/backup tests

**Interfaces:**
- Produces: safe upgrade that retains native tables, rows, and settings; new submissions use SAB only.

- [ ] **Step 1: Add RED upgrade fixture**

Create a representative current database containing `NativeUsenetJob`, native settings, and a tracked row with `TrackedDownloadMeta.download_client == "scarletx"`; run startup migration/seeding and assert all remain present and unchanged.

- [ ] **Step 2: Add SAB retention upgrade test**

Seed old `sabnzbd_url/api_key/category/priority` keys and prove startup no longer deletes them.

- [ ] **Step 3: Fix destructive current migration behavior**

The existing `migrate_to_scarletx()` logic must not delete tracked rows merely because `download_client != "scarletx"`; SAB rows are now valid. Replace any such filter with preservation of `scarletx` and `sabnzbd`, or remove unnecessary deletion entirely.

- [ ] **Step 4: Run upgrade tests and commit**

```bash
pytest tests/test_sabnzbd_downloader.py tests/test_backup_packaging_migration.py tests/test_hardening_039.py -q
git add scarletx/routes/application.py scarletx/settings_store.py tests
git commit -m "fix: preserve downloader state across SAB migration"
```

---

### Task 11: Update Docker/TrueNAS documentation and runtime assumptions

**Files:**
- Modify: `README.md`
- Modify: `docker-compose.yml` if `/downloads` semantics need clarification, not to embed SAB
- Modify: TrueNAS app/runtime documentation/configuration files that describe `/downloads`
- Test: packaging/TrueNAS contract tests

**Interfaces:**
- Produces: explicit external SAB requirement and identical completed-path mount guidance.

- [ ] **Step 1: Add RED documentation/package contracts**

Require README text that ScarletX connects to external SABnzbd, SAB and ScarletX share the same completed-download path, `localhost` is normally wrong between containers, and ScarletX no longer requires Usenet-provider credentials or PAR/unrar tools for SAB-managed downloads.

- [ ] **Step 2: Update docs/package comments**

Do not add a SAB service to ScarletX Compose. Document an example shared host dataset mapped identically into both independently managed containers.

- [ ] **Step 3: Run packaging tests and commit**

```bash
pytest tests -q -k 'packaging or truenas or sabnzbd'
git add README.md docker-compose.yml truenas tests
git commit -m "docs: document external SABnzbd deployment"
```

---

### Task 12: Full verification and PR

**Files:**
- No feature code unless verification exposes a defect.

- [ ] **Step 1: Run focused SAB suite**

```bash
pytest tests/test_sabnzbd_downloader.py -q
```

Expected: all pass.

- [ ] **Step 2: Run complete test suite on Python 3.12 locally/CI equivalent**

```bash
python -m pytest -q
ruff check .
python -m compileall -q scarletx
```

Expected: all pass.

- [ ] **Step 3: Run supported CI matrix**

Require GitHub Actions success on Python 3.11, 3.12, 3.13, dependency audit, backend/web container builds, performance baseline, and TrueNAS render validation.

- [ ] **Step 4: Verify key architecture by source search**

The active path must satisfy:

```text
scarletx/download_clients.py             no native_usenet import
scarletx/automation.py                   no native_usenet import
scarletx/download_processing.py          no NativeUsenetJob dependency for SAB state
normal lifespan                          no native_worker_loop task
normal Settings frontend                 no native NNTP provider controls
native_usenet.py + scarletx/usenet/      still present/importable
```

- [ ] **Step 5: Record real-SAB evidence honestly**

If a reachable SABnzbd integration environment is available, perform: Test Connection -> one test NZB submission -> queue observation -> history completion/failure reconciliation using a disposable legal test payload. If no real SAB instance is available, state that CI uses mocked SAB contract tests and do not claim live integration proof.

- [ ] **Step 6: Open implementation PR against latest `main`**

PR summary must call out: SAB-only active downloader, native runtime shelved not deleted, current activity/import/dashboard improvements preserved, upgrade safety, RED/GREEN evidence, full CI results, and any live-SAB limitation.
