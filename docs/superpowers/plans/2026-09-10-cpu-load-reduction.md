# ScarletX CPU Load Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce ScarletX idle/background CPU usage while preserving hourly monitored discovery and active download performance.

**Architecture:** Use adaptive active/idle completed-download polling, a 5-second idle native-downloader backoff, and durable AppSetting-based first-page cursors for monitored TPDB discovery. Existing locally monitored scene IDs continue into the normal automatic-search eligibility path, so release-ready and retry-eligible scenes are not lost when a TPDB entity is unchanged.

**Tech Stack:** Python 3.11-3.13, FastAPI, SQLAlchemy, asyncio, SQLite/PostgreSQL-compatible ORM patterns, pytest, GitHub Actions, TrueNAS app validation.

**Spec:** `docs/superpowers/specs/2026-09-10-cpu-load-reduction-design.md`

## Global Constraints
- Monitored performer/studio TPDB discovery remains every 60 minutes.
- Active download/import polling is 60 seconds; idle polling is 120 seconds.
- Native downloader queue polling backs off from 1 second to 5 seconds only while no queued job exists.
- Manual search/grab behavior is unchanged.
- Native downloader throughput is unchanged once work starts.
- Existing failed-download retry cap remains unchanged.
- No SABnzbd integration.

## Deterministic CPU-work reductions
- Idle completed-download/import polling: 30s -> 120s, reducing idle loop wakeups by 75%.
- Empty native Usenet queue polling: 1s -> 5s, reducing empty-queue DB wakeups by 80%.
- Unchanged monitored TPDB entities: first page only instead of all historical pages, with zero repeated scene metadata upserts for an unchanged head.
- TPDB entity refreshes use a bounded concurrency ceiling of 3 to avoid hourly all-core/network bursts.

---

### Task 1: Adaptive download/import polling

**Files:**
- Modify: `scarletx/download_processing.py`
- Test: `tests/test_cpu_load_reduction.py`

- [x] Add a failing test proving an idle processing pass requests 120-second polling and active work requests 60-second polling.
- [x] Confirm RED against the previous 30-second behavior.
- [x] Implement 60-second active / 120-second idle poll results; the existing application loop already honors returned `poll_seconds`.

### Task 2: Native downloader idle backoff

**Files:**
- Modify: `scarletx/usenet/worker.py`
- Test: `tests/test_cpu_load_reduction.py`

- [x] Add a failing test proving an empty native queue no longer wakes every second.
- [x] Confirm RED at the previous 1-second default.
- [x] Change only empty-queue polling to 5 seconds; active jobs continue directly into `process_job` without polling delay.

### Task 3: Durable incremental monitored discovery

**Files:**
- Modify: `scarletx/monitored_entities.py`
- Test: `tests/test_cpu_load_reduction.py`

- [x] Add a failing test proving a repeated unchanged TPDB result does not reprocess deep pages or scene metadata.
- [x] Confirm RED against the previous full-page refresh behavior.
- [x] Store the first-page TPDB scene-ID head in existing `AppSetting` rows, avoiding a schema migration.
- [x] Keep existing local scenes associated with monitored performers/studios in the hourly search candidate set.
- [x] Limit remote entity scans with an asyncio semaphore of 3.

### Task 4: Full verification

- [x] Preserve the existing 0.3.10 performance baseline suite as the regression benchmark.
- [ ] Run final Python 3.11/3.12/3.13 tests, Ruff, compilation, container builds, dependency audit, performance baseline, and TrueNAS validation on the final human-authored head.
- [ ] Review the final diff for scope and merge only if every gate is green.
