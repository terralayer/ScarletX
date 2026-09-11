# ScarletX CPU Load Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce ScarletX idle/background CPU usage while preserving hourly monitored discovery and active download performance.

**Architecture:** Add adaptive active/idle polling to completed-download processing and durable incremental cursors to monitored TPDB discovery. Feed only new/release-ready/retry-eligible scene IDs into the monitored automatic-search cycle, while bounding remote concurrency and batching DB checks.

**Tech Stack:** Python 3.11-3.13, FastAPI, SQLAlchemy, asyncio, SQLite/PostgreSQL-compatible ORM patterns, pytest, GitHub Actions, TrueNAS app validation.

**Spec:** `docs/superpowers/specs/2026-09-10-cpu-load-reduction-design.md`

## Global Constraints
- Monitored performer/studio TPDB discovery remains every 60 minutes.
- Active download/import polling is 60 seconds; idle polling is 120 seconds.
- Manual search/grab behavior is unchanged.
- Native downloader throughput is unchanged.
- Existing failed-download retry cap remains unchanged.
- No SABnzbd integration.

---

### Task 1: Adaptive download/import polling

**Files:**
- Modify: `scarletx/download_processing.py`
- Modify: `scarletx/routes/application.py`
- Test: `tests/test_download_pipeline.py`

**Interfaces:**
- Produces: processing result field `active: bool` and helper selecting 60s active / 120s idle delay.

- [ ] Add a failing test proving an idle processing pass requests 120-second polling and active work requests 60-second polling.
- [ ] Run the focused test and confirm RED.
- [ ] Implement minimal adaptive poll result/loop logic.
- [ ] Run focused tests and confirm GREEN.

### Task 2: Durable incremental monitored discovery

**Files:**
- Modify: `scarletx/models.py`
- Modify: `scarletx/migrations.py`
- Modify: `scarletx/monitored_entities.py`
- Test: `tests/test_monitored_entity_discovery.py`

**Interfaces:**
- Produces: durable per-entity last successful scan state; discovery result containing only scene IDs requiring downstream search.

- [ ] Add failing tests proving a repeated unchanged TPDB result does not re-emit scene IDs for search and that scan state survives a new DB session.
- [ ] Run focused tests and confirm RED.
- [ ] Add the scan-state model/migration and minimal incremental discovery logic.
- [ ] Run focused tests and confirm GREEN.

### Task 3: Bounded remote concurrency and batched search eligibility

**Files:**
- Modify: `scarletx/monitored_entities.py`
- Modify: `scarletx/automation.py`
- Test: `tests/test_monitored_entity_discovery.py`
- Test: `tests/test_automation.py`

**Interfaces:**
- Consumes: scene IDs emitted by incremental discovery.
- Produces: bounded TPDB work and batched failed/active/media eligibility filtering before indexer search.

- [ ] Add failing tests for concurrency ceiling and single batched eligibility query behavior where observable.
- [ ] Run focused tests and confirm RED.
- [ ] Implement a small fixed asyncio semaphore and batched scene/download state lookup.
- [ ] Run focused tests and confirm GREEN.

### Task 4: Benchmark and full verification

**Files:**
- Modify: `tools/benchmark_0310.py`
- Test: existing full suite.

- [ ] Add benchmark counters for idle processing and unchanged repeated monitored discovery.
- [ ] Run the benchmark and capture results.
- [ ] Run Python 3.11/3.12/3.13 tests, Ruff, compilation, container builds, dependency audit, performance baseline, and TrueNAS validation.
- [ ] Review the final diff for scope and merge only if every gate is green.
