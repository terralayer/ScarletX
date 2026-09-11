# ScarletX Monitored Entity Hourly Discovery Design

## Goal
Persist Monitor All choices for performers and studios, discover newly published and future TPDB scenes for those monitored entities every hour, add future scenes to Upcoming Calendar, automatically search/grab monitored scenes when Usenet releases become available, fix remaining same-view navigation races, and show studio names beneath titles on Downloads.

## Existing Building Blocks
- `Performer.monitored`, `Studio.monitored`, and `Scene.monitored` are durable database fields.
- ScarletX already has an automatic-search scheduler and `automatic_search_cycle()` for monitored scenes.
- TPDB scene search already supports performer and site/studio filters.
- Calendar already reads monitored scenes by `release_date`.
- Downloads serialize tracked downloads through `_tracked_download_rows()`.
- PR #60 added cross-view render guards, but same-view async requests can still overwrite newer renders.

## Design

### 1. Durable monitored-entity discovery
Create a focused `monitored_entities.py` service. Its hourly cycle loads all monitored performers and studios, queries TPDB for scenes associated with each TPDB ID, deduplicates results by TPDB scene ID, and upserts them through the existing adult-only service functions. Newly discovered scenes inherit `monitored=True` when they were discovered from a monitored performer or studio.

The cycle must be idempotent. Existing scenes are refreshed rather than duplicated. Existing explicit scene monitoring is never cleared. Performer/studio relationships and studio metadata are updated from TPDB results using existing upsert paths.

Failures for one performer or studio must not abort the entire cycle. Record per-entity errors and continue.

### 2. Hourly scheduling
Use the existing application lifespan scheduler pattern. Add a monitored-entity discovery loop fixed at 60 minutes. It runs independently from Newznab automatic search so a TPDB outage cannot prevent searches for already-known monitored scenes.

The cycle runs shortly after startup and then hourly. No extra external scheduler is required.

### 3. Upcoming Calendar
Future TPDB scenes discovered from monitored performers/studios are stored as normal monitored `Scene` rows with their TPDB `release_date`. The existing calendar query therefore includes them automatically. No duplicate calendar storage is introduced.

### 4. Automatic downloading
After discovery completes, the existing automatic search path remains authoritative for release selection and native Usenet download submission. Newly discovered past/current scenes can be searched immediately after a discovery cycle. Future scenes remain in the calendar and are eligible for hourly searches once their release date is today or earlier.

Automatic search must skip future-dated scenes to avoid pointless indexer traffic before release day.

### 5. Monitor All semantics
Monitor All on a performer or studio must persist the entity's `monitored=True` database state before background scene discovery/search starts. Repeated Monitor All calls remain idempotent. Explicit unmonitoring turns off future entity discovery but does not delete already-imported scenes.

### 6. Navigation responsiveness
Introduce a monotonic frontend render generation/token. Every navigation, entity/profile/detail render, and search transition captures the current generation. After every awaited read, DOM mutation is allowed only if both the expected view and generation still match. This fixes same-view races such as performer A -> performer B, studio A -> studio B, rapid searches, and library/detail switches.

Error handlers must use the same token check before painting shared DOM.

### 7. Downloads studio label
Bulk-load studios for tracked-download scenes in `_tracked_download_rows()` and include a `studio` field. The Downloads row renders the studio name directly beneath the scene/title text. The serializer must avoid N+1 queries.

## Constraints
- Adult studio-release filtering remains unchanged.
- Native ScarletX downloader remains unchanged.
- No SABnzbd integration.
- Do not create duplicate scene/calendar/download pipelines.
- Preserve existing persistent data and migrations.
- Hourly means 60 minutes.

## Verification
Add regression tests for persisted entity monitoring, TPDB discovery/deduplication, future-calendar visibility, future-scene search suppression, release-day automatic grabbing, per-entity failure isolation, same-view stale-render suppression, and Downloads studio serialization/rendering. Run Python 3.11/3.12/3.13 tests, Ruff, source compilation, container builds, dependency audit, performance baseline, and TrueNAS validation before merge.
