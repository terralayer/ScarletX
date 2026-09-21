# Library Reliability Implementation Plan

> **For agentic workers:** Use test-first implementation with independent bounded backend work in parallel and one integrated review. Preserve all pre-existing local work.

**Goal:** Complete local-first discovery, persistent download pause, visible refresh status, consistent paging, and targeted UI consolidation.

**Architecture:** Retain FastAPI/SQLite and the existing vanilla-JavaScript UI. Add explicit search sources and durable pause state using existing storage; put shared UI behavior in dedicated modules instead of additional competing overrides.

**Tech Stack:** Python, FastAPI, SQLAlchemy, SQLite, JavaScript, pytest/Node, Docker/nginx.

**Spec:** `docs/superpowers/specs/2026-09-19-library-reliability-design.md`

## Global Constraints

- Preserve existing library, settings, monitoring state, authentication, and unrelated dirty changes.
- No commits/resets or new checkout that omits existing uncommitted work; no live Pause/Resume actions.
- Keep external results locally; use local results first and remote discovery only through explicit UI action.
- New scripts must be packaged and loaded in deterministic order.
- Keep each parallel worker in its assigned functions/files; main agent owns shared UI integration.

## Review Focus

- Search already has partial local matches: online discovery must still find all provider pages.
- Provider fails mid-search: previous results remain usable and failed page can be retried.
- New downloads arrive or service restarts during global pause: transfers must remain held.
- User navigates away or rapidly changes pages: stale responses must neither repaint nor scroll another view.
- A refresh fails after a successful check: retain last success without falsely marking current discovery complete.

### Task 1: Search sources and durable provider-page caching

**Files:** `scarletx/performer_search.py`, `scarletx/studio_search.py`, search imports/routes in `scarletx/routes/application.py`, `tests/test_performer_search_responsiveness.py`, new search tests as needed. Main integrates `frontend/entity_search.js` and removes obsolete search definitions.

**Interfaces:** Existing routes accept `source=auto|local|online`; response unchanged. `auto` retains compatibility. Local never calls provider; online loads saved query/page before provider.

- [x] Write tests using existing SQLite/provider fixtures. Pin local-empty no-network and online with partial local matches, page-two totals/order, repeated page no network, preserved richer metadata/monitoring, and failed fetch retry.
  ```python
  result = await application.search_performers('New Person', page=1, settings=Settings(), source='local')
  assert result.items == []
  assert provider.calls == []
  ```
- [x] Run `.venv/bin/pytest -q tests/test_performer_search_responsiveness.py`; observe the new source-contract tests fail before implementation.
- [x] Implement explicit route branching and atomic persisted query/page caches using current studio cache pattern. Maintain original totals/order independently of locally accumulated rows.
  ```python
  if source == 'local':
      return await asyncio.to_thread(local_performer_search, SessionLocal, q, page)
  ```
- [x] Add Node UI behavior tests first: local initial URL, Find more online URL, navigation through search pages, failed/stale load preserving results, existing library return.
- [x] Implement single authoritative `entity_search.js`; remove replaced app/navigation search bodies, package/load module, rerun focused tests.

### Task 2: Durable Pause All

**Files:** `scarletx/downloader_state_hotfix.py`, `scarletx/usenet/worker.py` (and narrow supporting settings/control module if needed), downloader tests. Main integrates `frontend/download_controls.js`, removing superseded toolbar helpers from app.js.

**Interfaces:** GET `/api/downloads/native/control` -> `{paused: bool}`. POST pause-all -> paused count/global flag. POST resume-all -> resumed count/global flag. Existing individual routes remain compatible except global pause blocks individual resume with a useful conflict message.

- [x] Write regression tests with temporary DBs: paused setting survives a new session; newly enqueued/claimed jobs cannot transfer; resume releases paused work only; no-job pause still persists; post-processing remains unchanged; individual resume cannot bypass global flag.
  ```python
  pause_all_native_downloads(db)
  assert native_download_control(db)['paused'] is True
  ```
- [x] Run new tests and existing downloader state tests; verify missing persistent behavior fails.
- [x] Persist flag transactionally and enforce it at enqueue and worker claim/process boundaries. Add bulk resume route without live side effects during import/startup.
- [x] Main writes UI tests for persistent label on reload, bulk resume call, disabled pending state, and failures restoring retry; implement controller and run focused tests.

### Task 3: Catalog status that reflects actual progress

**Files:** `scarletx/scene_catalog.py`, only `initProfileSceneCatalog` in `frontend/navigation_error_overrides.js`, catalog/profile tests.

**Interfaces:** Status includes ISO/null queued/finished timestamps and `last_success_at`; all existing fields remain. UI consumes these fields without blocking saved scene rendering.

- [x] Write status tests for never-checked, active, completed and failed-after-success.
  ```python
  status = scene_catalog_status(db, 'performer', 'example')
  assert status['last_success_at'] is None
  ```
- [x] Observe new tests fail, then implement bounded status lookup/serialization and persistent last-success reporting.
- [x] Add Node behavior coverage for progress/failed/completed text; update toolbar to show pages/scenes/last checked accurately, with existing retry and cancellation behavior intact.
- [x] Run catalog completeness and profile UI tests.

### Task 4: Shared pagination and removal of overlapping UI implementations

**Files:** `frontend/pagination.js`, `frontend/app.js`, `frontend/ui_overrides.js`, `frontend/activity_history_overrides.js`, `frontend/wanted_bulk_overrides.js`, `frontend/ui_overrides.css`, packaging/index, pagination/runtime tests.

**Interfaces:** Shared async page-transition helper accepts list identity, load operation, rollback, current-page guard, and target selector. Each handler reports success only when its relevant response is displayed.

- [x] Add behavior tests for Media Library, Completed/Failed, History, Wanted: success scrolls below header; failure rolls back without scrolling; navigation/racing response does not repaint stale data.
- [x] Run tests and observe failures for old missing scroll/rollback behavior.
- [x] Implement shared helper and use it in existing entity/queue handlers as well as remaining pagers. Keep pagination under each list, centered and full width.
- [x] Remove duplicate active queue/media-library definitions in app.js where later modules are the actual implementation; consolidate toolbar/search into Task 1/2 modules. Update tests to exercise authoritative loaded modules instead of removed source bodies.
- [x] Run relevant runtime and UI contract tests plus JavaScript syntax checks.

### Task 5: Integrated verification, review, and local rollout

- [x] Run `.venv/bin/pytest -q`, `.venv/bin/ruff check scarletx tests tools`, `node --check` on changed JS, and `git diff --check`. Expected: all pass; record existing warnings separately.
- [x] Independent scoped review of all five requirements and failure modes; fix important findings with regression tests.
- [x] Build backend/web images with the existing mac compose files. Verify deployment mounts and settings; take existing supported backup before replacing backend if needed.
- [x] Update existing backend service and web preview without clearing volumes; check health and browser paging/search/status. Do not trigger live downloads or external discovery.
- [x] Report delivered behavior, actual tests, and any remaining limitations concisely.

## Progress / decisions

- Planning: user approved all listed improvements and previously requested continuous action without repeated approval. Documented design/plan before product edits.
- Workspace: existing `/Users/troy/ScarletX` contains the user's active uncommitted implementation. Work in place rather than create a HEAD-only worktree that loses these changes; no commits or resets.
- Baseline from immediately preceding turn: 708 tests passed, lint/syntax/build passed. Re-run full suite after integration.

## Final verification and rollout

- All five implementation slices completed in the existing checkout; no commits, resets, or clearing of user data.
- Independent review identified three pagination edge cases. Regression tests reproduced them, then verified boundary-button restoration, successful-paint-only clamping, and coordination of live queue updates with page transitions. Reviewer confirmed all three resolved.
- Final complete suite: **749 passed**, with four pre-existing dependency deprecation warnings. Full Ruff check, every frontend JavaScript syntax check, and `git diff --check` passed. Backend and web images built successfully.
- Created supported backup `/backups/scarletx-20260920-052506-7fa29938e3d24cb68a476c97d705d733.db` (41,676,800 bytes) with matching secret-key backup. Extra backup did not rotate/delete existing backups.
- Updated only the existing backend service and published packaged assets to `scarletx-web-preview` on `127.0.0.1:8691`; authentication boot preserved. Backend healthy; original config/download/backup volumes and `/Users/troy/ScarletXMedia` mount unchanged. Immediately before/after restart: 80 settings, 15,695 scenes, 4,617 performers, 888 studios; global pause remained false. Existing background jobs may continue adding records normally.
- Live browser verified saved performer page 2, local search page 2 and Find more online control, centered pagers, active/completed/history independent page 2, and successful scroll positions (app 96px, download sections 100px). Verified a previously completed performer catalog shows four pages, 270 saved scenes, last successful check, and year groups. No browser errors recorded.
- Media Library/Wanted failure/race cases were covered by isolated runtime tests, not live queue mutations. Persistent pause/restart and external-provider behavior were tested with isolated databases/fake providers. No live Pause/Resume, external discovery, or refresh operation was triggered for testing. Temporary verification browser tab closed.
