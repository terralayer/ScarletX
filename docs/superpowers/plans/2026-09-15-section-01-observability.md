# Section 1 Observability Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add low-overhead runtime observability around the existing 0.3.10 benchmark baseline without changing ScarletX 0.4.0 behavior or deployment topology.

**Architecture:** A process-local `RuntimeObservability` collector owns bounded counters/timers and recent slow-query summaries. FastAPI middleware records request latency, SQLAlchemy engine hooks record query latency, TPDB network calls record remote latency, and an API router returns a snapshot augmented with queue/process/disk metrics computed only when requested.

**Tech Stack:** Python 3.11+, FastAPI/Starlette, SQLAlchemy 2 events, stdlib `logging`, `time`, `threading`, `collections`, `os`, `shutil`, SQLite.

**Spec:** `docs/superpowers/specs/2026-09-15-butter-smooth-reliability-design.md`

## Global Constraints

- Keep application version exactly `0.4.0`.
- Do not add a new runtime dependency.
- Keep `/api/health` response contract unchanged and lightweight.
- Metrics must not include credentials, request bodies, query parameters, SQL parameters, NZB URLs, or TPDB authorization data.
- All in-memory history must be explicitly bounded.
- Instrumentation must never make an application request or database query fail.

---

### Task 1: Runtime collector contract

**Files:**
- Create: `tests/test_observability.py`
- Create: `scarletx/observability.py`

**Interfaces:**
- Produces: `runtime_observability: RuntimeObservability`.
- Produces: `RuntimeObservability.record_request(method: str, path: str, status_code: int, elapsed_seconds: float) -> None`.
- Produces: `RuntimeObservability.record_db_query(statement: str, elapsed_seconds: float) -> None`.
- Produces: `RuntimeObservability.record_tpdb(elapsed_seconds: float, *, success: bool, cache: str) -> None`.
- Produces: `RuntimeObservability.snapshot() -> dict[str, object]`.

- [ ] **Step 1: Write failing collector tests**

Add tests that reset an isolated collector, record successful/error requests, one normal query and one slow query, then assert counts, max/average timings, error count, and a bounded secret-safe slow-query record containing only operation/table/duration fields. Add a TPDB timing test that distinguishes network success/failure and cache source.

- [ ] **Step 2: Run the focused tests and observe RED**

Run: `python -m pytest tests/test_observability.py -q`
Expected: import failure because `scarletx.observability` does not yet exist.

- [ ] **Step 3: Implement the bounded collector**

Use a lock-protected dictionary for counters/aggregates and `deque(maxlen=20)` for slow queries. Default slow-query threshold is `SCARLETX_SLOW_QUERY_MS` or 250 ms. Extract only the SQL verb and table token (`FROM`, `INTO`, `UPDATE`, `JOIN`) for diagnostics; never retain SQL parameters or literal values. Emit slow-query logs as a JSON object through the `scarletx.observability` logger.

- [ ] **Step 4: Re-run focused tests**

Run: `python -m pytest tests/test_observability.py -q`
Expected: collector tests pass.

---

### Task 2: Request and database instrumentation

**Files:**
- Modify: `tests/test_observability.py`
- Modify: `scarletx/observability.py`
- Modify: `scarletx/app.py`

**Interfaces:**
- Produces: `install_observability(app: FastAPI, engine: Engine) -> None` and installs at most once per app/engine.

- [ ] **Step 1: Write failing integration tests**

Add a FastAPI test app using the installer. Assert one request increments request totals and a trivial SQLAlchemy `SELECT 1` increments DB query totals. Install twice and assert instrumentation is not duplicated.

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_observability.py -q`
Expected: failure because `install_observability` is missing.

- [ ] **Step 3: Implement middleware and SQLAlchemy timing hooks**

Use `time.perf_counter()` around `call_next`. The middleware records status 500 on raised exceptions and re-raises. SQLAlchemy `before_cursor_execute` pushes a start time onto `connection.info`; `after_cursor_execute` pops and records it. Event hooks swallow observability errors. Mark app/engine objects so repeat installation does not double-register.

- [ ] **Step 4: Wire the installer in `scarletx/app.py`**

Import `engine` from `scarletx.db`, import `install_observability`, and install after the legacy app is composed. No route behavior changes.

- [ ] **Step 5: Re-run focused tests**

Run: `python -m pytest tests/test_observability.py -q`
Expected: PASS.

---

### Task 3: Metrics snapshot endpoint

**Files:**
- Modify: `tests/test_observability.py`
- Create: `scarletx/observability_routes.py`
- Modify: `scarletx/app.py`

**Interfaces:**
- Produces: `GET /api/system/metrics` returning `requests`, `database`, `tpdb`, `queues`, `downloads`, `imports`, `process`, and `disk` sections.

- [ ] **Step 1: Write failing route tests**

Build an isolated database with queued/downloading/imported fixtures. Assert the endpoint reports native/background/tracked queue counts, summed active `speed_bps`, recent queue-wait/import-latency measurements, bounded process memory/CPU/uptime values, and disk capacity. Assert `/api/health` still returns its existing keys and `version == "0.4.0"`.

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_observability.py -q`
Expected: 404 for `/api/system/metrics`.

- [ ] **Step 3: Implement snapshot router**

Create an APIRouter whose dependency uses `get_session`. Compute operational queue aggregates only when metrics are requested. Sample at most 100 recent queue-wait/import-latency rows. Read current RSS from `/proc/self/statm` when available, with a safe fallback; use process time divided by uptime as a low-overhead lifetime CPU signal. Use `shutil.disk_usage` on the database/config working path. Any unavailable metric is `null` rather than an endpoint failure.

- [ ] **Step 4: Register the router**

Include the router from `scarletx/app.py`. It remains under the existing API authentication middleware when authentication is enabled; `/api/health` remains the only lightweight health route.

- [ ] **Step 5: Re-run focused tests**

Run: `python -m pytest tests/test_observability.py -q`
Expected: PASS.

---

### Task 4: TPDB network latency instrumentation and regression gate

**Files:**
- Modify: `tests/test_observability.py`
- Modify: `scarletx/tpdb.py`

**Interfaces:**
- Consumes: `runtime_observability.record_tpdb(...)`.

- [ ] **Step 1: Write failing TPDB timing test**

Use `httpx.MockTransport`/the existing test transport pattern, clear the in-memory/disk cache for the request key, perform one network `_get`, then assert one network TPDB timing sample. Perform the same `_get` again and assert the network count does not increase.

- [ ] **Step 2: Run tests and observe RED**

Run: `python -m pytest tests/test_observability.py -q`
Expected: TPDB network timing count remains zero.

- [ ] **Step 3: Time only the actual HTTP attempt**

Wrap each `self.client.get(...)` attempt in `time.perf_counter()` and record success/failure in a `finally` block. Record memory/disk cache hits separately without pretending they are network requests.

- [ ] **Step 4: Run focused and existing TPDB-cache tests**

Run: `python -m pytest tests/test_observability.py tests/test_tpdb_cache.py -q`
Expected: PASS.

---

### Task 5: Full verification

**Files:** none beyond prior tasks.

- [ ] **Step 1: Run repository tests and lint**

Run: `python -m pytest -q`
Run: `python -m ruff check scarletx tests tools`
Run: `python -m compileall -q scarletx tests tools`

- [ ] **Step 2: Run deterministic performance suite**

Run: `python tools/benchmark_0310.py --scenario all --iterations 5 --json /tmp/scarletx-observability.json`
Expected: all scenarios complete and no established guard regresses.

- [ ] **Step 3: Verify version is unchanged**

Run: `git diff main...HEAD -- BUILD-INFO.txt RELEASE-NOTES-0.4.0.md scarletx/tpdb.py start-scarletx.sh Start-ScarletX.ps1`
Expected: no version string changes; `scarletx/tpdb.py` may differ only for observability instrumentation.
