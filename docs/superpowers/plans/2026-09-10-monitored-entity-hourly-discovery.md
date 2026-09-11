# Monitored Entity Hourly Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make monitored performers/studios durable hourly TPDB discovery sources, surface future scenes in Upcoming, automatically grab available releases, eliminate remaining same-view UI races, and show studio names on Downloads.

**Architecture:** Add one focused monitored-entity discovery service that reuses TPDB and existing upsert/search/download paths. Keep TPDB discovery independent from Newznab release search, coordinate both from the existing lifespan scheduler, and use a frontend render generation token to reject stale async results.

**Tech Stack:** Python 3.11-3.13, FastAPI, SQLAlchemy, asyncio, vanilla JS, pytest, Docker/TrueNAS.

**Spec:** `docs/superpowers/specs/2026-09-10-monitored-entity-hourly-discovery.md`

## Global Constraints
- Hourly discovery interval is 60 minutes.
- `Monitor All` persists performer/studio monitoring until explicitly unmonitored.
- Future scenes are durable monitored `Scene` rows and use the existing calendar.
- Native ScarletX downloader remains authoritative; no SABnzbd integration.
- Adult studio-only filtering remains unchanged.
- No duplicate discovery/calendar/download pipelines.

---

### Task 1: Monitored entity discovery service
**Files:** Create `scarletx/monitored_entities.py`; Test `tests/test_monitored_entity_discovery.py`.
**Interfaces:** Produce `async monitored_entity_discovery_cycle(session_factory, settings) -> dict`.
- [ ] Add failing tests for monitored performer/studio TPDB scene discovery, dedupe by TPDB scene ID, persistence across sessions, and per-entity failure isolation.
- [ ] Implement paged performer/studio TPDB discovery using `ThePornDBClient`, resolving canonical studio IDs to TPDB searchable site IDs where needed.
- [ ] Upsert scenes through `upsert_scene(..., monitored=True)` and preserve explicit entity monitor flags.
- [ ] Return checked/discovered/created/refreshed/error counts.
- [ ] Run focused tests and commit.

### Task 2: Hourly scheduling and release-day behavior
**Files:** Modify `scarletx/routes/application.py`, `scarletx/automation.py`; Test `tests/test_monitored_entity_scheduler.py`, automation tests.
**Interfaces:** Scheduler calls discovery every 3600 seconds; `automatic_search_cycle()` skips `release_date > today`.
- [ ] Add failing tests proving future scenes are not searched before release day and newly discovered current/past scenes are eligible.
- [ ] Add an independent lifespan task for monitored-entity discovery with immediate startup run followed by 3600-second intervals.
- [ ] Keep automatic search independent; after a successful discovery pass invoke existing automatic search when enabled so newly available scenes can queue without another hour delay.
- [ ] Add future-date guard to automatic search.
- [ ] Run focused tests and commit.

### Task 3: Monitor All persistence and Upcoming Calendar
**Files:** Modify relevant monitor endpoints in `scarletx/routes/application.py`; Test existing/new monitoring and calendar tests.
**Interfaces:** Monitor All writes `Performer.monitored=True` / `Studio.monitored=True` before launching background discovery/search.
- [ ] Add failing tests for persistent Monitor All state after request/session restart.
- [ ] Verify repeated Monitor All is idempotent and explicit unmonitor disables later entity discovery.
- [ ] Add calendar test showing future discovered monitored scenes are returned by `calendar_items()`.
- [ ] Implement minimal endpoint adjustments if current routes do not already persist before background work.
- [ ] Run focused tests and commit.

### Task 4: Same-view navigation generation guard
**Files:** Modify `frontend/app.js`, `frontend/ui_overrides.js` and any active override file owning entity/profile navigation; Test `tests/test_ui_navigation_responsiveness.py`.
**Interfaces:** Add global monotonic render generation helpers; each async render captures a generation and validates it after awaits and in catches.
- [ ] Add failing source/regression tests for performer->performer, studio->studio, search->search, entity detail, and Library/detail stale writes.
- [ ] Increment render generation on navigation/render initiation.
- [ ] Reject stale success and error paints when generation or expected view no longer matches.
- [ ] Preserve queue SSE and write actions.
- [ ] Run focused tests and commit.

### Task 5: Downloads studio name
**Files:** Modify `scarletx/routes/application.py` serializer and frontend Downloads rendering; Test download serializer/UI tests.
**Interfaces:** `_tracked_download_rows()` returns `studio: str | None` using bulk studio loading.
- [ ] Add failing serializer test requiring studio name with no per-row studio query.
- [ ] Add failing frontend test requiring studio beneath title.
- [ ] Bulk-load required `Studio` rows and emit `studio` field.
- [ ] Render studio on its own subordinate line beneath scene/title.
- [ ] Run focused tests and commit.

### Task 6: Full verification and merge
**Files:** No production changes unless verification exposes a defect.
- [ ] Run full pytest matrix on Python 3.11/3.12/3.13.
- [ ] Run Ruff and source compilation.
- [ ] Run container builds, dependency audit, and performance baseline.
- [ ] Run TrueNAS validation.
- [ ] Review final diff for unrelated changes and N+1 regressions.
- [ ] Merge only with all required checks green.
