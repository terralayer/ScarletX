# ScarletX SABnzbd Downloader Decoupling Design

Date: 2026-09-07
Status: Proposed
Branch: `design/sabnzbd-downloader-decoupling`

## Summary

ScarletX will stop acting as its own active Usenet downloader. Search, monitoring, RSS/manual grabs, metadata matching, import, naming, and library management remain ScarletX responsibilities. SABnzbd becomes the only active download engine for the current product line.

The existing built-in NNTP/downloader implementation will be shelved rather than deleted. Its source code and compatibility database artifacts remain in the repository so it can be revived later, but normal ScarletX runtime startup, settings, queue behavior, submission, and status surfaces must no longer depend on it.

The architectural boundary is a small downloader-client interface owned by ScarletX. Core application flows submit releases and query download state through that boundary without importing or understanding SABnzbd-specific or native-downloader internals.

## Goals

1. Decouple ScarletX discovery/monitoring/import logic from the built-in downloader.
2. Make SABnzbd the sole active downloader for Usenet releases.
3. Preserve existing ScarletX post-download behavior: matching, import, naming, library updates, monitored-state updates, and cleanup.
4. Preserve old native-downloader data and source for compatibility and possible future restoration.
5. Make future downloader replacements additive rather than another whole-app refactor.
6. Keep upgrades from existing 0.3.10 installations safe and avoid destructive migrations.

## Non-goals

1. Do not improve or repair the native NNTP implementation in this change.
2. Do not delete `native_usenet_jobs`, old downloader history, or native-downloader source files.
3. Do not make ScarletX perform PAR2 repair or archive extraction for SABnzbd downloads. SABnzbd owns download, verification/repair, and unpacking.
4. Do not add qBittorrent, torrents, or a generic torrent abstraction.
5. Do not embed or launch a SABnzbd container from ScarletX itself. ScarletX connects to an externally managed SABnzbd instance.
6. Do not require webhook support from SABnzbd for correctness; polling through the SAB API is the baseline contract.

## Target Architecture

```text
Indexer / Search / RSS / Monitoring
              |
              v
      Download Service
              |
              v
      DownloadClient API
              |
              +---- SABnzbdClient  (active)
              |
              `---- NativeUsenet   (shelved, not wired into runtime)

SABnzbd
  |- receives NZB/NZB URL
  |- downloads
  |- verifies/repairs
  `- unpacks
              |
              v
     Download Tracking
              |
       completed path
              |
              v
  ScarletX Import Pipeline
  |- identify/match scene
  |- rename and move/copy/hardlink according to ScarletX import settings
  |- update library/database
  |- update monitored/download state
  `- cleanup tracking state
```

## Downloader Boundary

`scarletx/download_clients.py` becomes a dispatcher/facade rather than importing the native Usenet worker directly.

The active abstraction must cover the behaviors ScarletX actually needs, not mirror every SABnzbd API feature. The expected contract is conceptually:

```python
class DownloadClient(Protocol):
    @property
    def name(self) -> str: ...

    async def test_connection(self) -> ClientHealth: ...

    async def submit_release(
        self,
        release: NewznabRelease,
        *,
        name: str | None = None,
        category: str | None = None,
    ) -> SubmittedDownload: ...

    async def get_downloads(
        self,
        external_ids: Sequence[str],
    ) -> Sequence[DownloadStatus]: ...
```

The exact Python shape may use classes or functions to match existing project style, but application callers must depend only on the stable facade and neutral result models.

Neutral models must include enough information for ScarletX to operate independently of SAB terminology:

- external download ID
- client name
- display name
- state: queued, downloading, paused, completed, failed, removed/unknown
- progress percent when available
- total/downloaded size when available
- error/failure text when available
- completed output path when available

SAB-specific values such as `nzo_id`, queue slots, history status strings, and SAB stage names are translated inside the SAB client.

## SABnzbd Client

Add a focused SABnzbd implementation, preferably `scarletx/downloaders/sabnzbd.py` or an equivalent downloader package created during implementation.

### Configuration

ScarletX stores and exposes:

- `sabnzbd_url`
- `sabnzbd_api_key` — encrypted secret
- `sabnzbd_category` — default `scarletx`
- `sabnzbd_priority` — default normal

The Settings UI includes a Test Connection action. Test Connection must validate that ScarletX can reach the configured SAB instance and authenticate successfully without submitting a download.

`download_client_mode` is unnecessary while SABnzbd is the only supported active client. Existing legacy values may be ignored/removed from runtime configuration rather than preserved as an active selector.

The existing settings migration currently treats SAB keys as legacy/deleted values. That behavior must change so SAB settings are retained and seeded through the normal settings system. `sabnzbd_api_key` must be included in secret encryption handling.

### Submission

ScarletX submits a Newznab release to SABnzbd using the release download URL when supported by the current API flow. If URL submission is not reliable for a given indexer/SAB combination, the implementation may fetch the NZB through ScarletX and upload it to SAB, but that fallback must remain inside the SAB client and not leak into search/monitoring code.

Submission parameters:

- NZB URL or NZB payload
- requested ScarletX name
- configured/category override
- configured priority

On success, ScarletX stores the SAB external ID returned by SAB (`nzo_id` or equivalent) in ScarletX's neutral download tracking record.

Submission is considered unsuccessful if SAB does not positively accept the item. Network errors, API errors, authentication errors, and malformed responses become `DownloadClientError` values with useful user-facing messages and sanitized logs.

### Queue and History State

SAB queue and history are separate API surfaces. The client adapter normalizes both into one ScarletX lifecycle.

Expected mapping:

- SAB queue item waiting/downloading/paused -> queued/downloading/paused
- SAB history completed -> completed
- SAB history failed -> failed
- known ScarletX external ID absent from both queue and history -> unknown/removed after a bounded reconciliation policy

ScarletX must not assume completion solely because an item disappears from SAB's queue.

### Completion Path

The SAB history record's final path is authoritative for the downloaded/unpacked payload. ScarletX passes that path into the existing import pipeline.

For containerized deployments, ScarletX and SABnzbd must be configured with a shared completed-download mount whose in-container path is either identical or explicitly mapped. The first implementation should prefer identical paths because it eliminates path translation bugs. Documentation and TrueNAS configuration must state this requirement clearly.

ScarletX does not import until SAB reports a successful completion state. Failed SAB jobs remain failed and visible; they are not sent into the import pipeline.

## ScarletX Download Tracking

The current application should use a client-neutral tracking record for downloads it submitted. If an existing `TrackedDownload` model already provides the required neutral fields, evolve/reuse it instead of introducing a redundant table.

Required persisted data:

- ScarletX tracking ID
- downloader client (`sabnzbd`)
- external client ID
- source release/indexer identity when already tracked today
- scene/performer/studio association needed by monitoring flows
- requested name/category if useful for diagnostics
- state
- progress
- completed path
- last client check timestamp
- error/failure reason
- creation/update timestamps

Do not delete native downloader job rows. Native job tables become historical compatibility data and are not used for new submissions.

## Polling and Reconciliation

The existing download polling service remains a ScarletX service, but its job changes from inspecting native-worker internals to asking the active `DownloadClient` for state.

Baseline behavior:

1. Load ScarletX tracked downloads that are non-terminal or awaiting import.
2. Query SAB efficiently in batches where practical rather than making one API request per tracked job.
3. Normalize SAB queue/history state.
4. Persist meaningful state/progress changes using the existing throttling strategy where applicable.
5. When SAB reports complete, enqueue/perform the existing ScarletX import flow exactly once.
6. When SAB reports failed, persist the failure and expose it to the UI.
7. Recover cleanly after ScarletX restart by reconciling persisted external IDs against SAB queue/history.

Polling intervals should reuse `download_poll_seconds` unless implementation evidence shows a separate setting is necessary.

## Import Ownership

SABnzbd owns:

- NNTP connections
- article retrieval
- temporary/incomplete storage
- PAR verification/repair
- archive extraction
- download retry behavior
- download speed limiting

ScarletX owns:

- search and release selection
- monitored scene/performer/studio logic
- download submission
- application-level tracking
- deciding whether a SAB completion corresponds to a ScarletX-managed item
- media identification/probing required for import
- naming
- copy/move/hardlink behavior
- library/database updates
- monitored-state updates
- post-import cleanup controlled by ScarletX settings

This boundary must be reflected in UI labels and documentation so ScarletX does not expose native NNTP concepts while SAB is active.

## Shelving Native Usenet

The native downloader is disconnected in stages without destructive deletion.

Runtime behavior to disable/remove from normal application flow:

- automatic startup of native NNTP worker(s)
- native provider readiness checks as the download-client readiness signal
- native queue submission through `enqueue_url`
- native queue as the primary Downloads UI source
- native provider configuration in the normal Settings UI
- native repair/unpack/speed controls in the normal Settings UI
- application status that presents native NNTP provider state as required for ScarletX health

Retain for compatibility/future restoration:

- `scarletx/native_usenet.py`
- `scarletx/usenet/` implementation
- native job model/table and migrations
- relevant security helpers needed by that dormant code
- historical tests where cheap to retain

Tests and benchmarks that specifically assert active-native-downloader behavior should be moved to a dormant/native-specific scope or replaced where they validate the now-active product path.

No new product behavior should import native downloader functions outside the dormant native package.

## UI Changes

### Settings

Replace the active native Usenet provider settings section with a `SABnzbd` section containing:

- URL
- API key
- category
- priority
- Test Connection
- connection state/result

Do not ask users for Usenet provider credentials in ScarletX. Those belong in SABnzbd.

### Downloads

The ScarletX Downloads page remains useful but becomes an application-level view of downloads ScarletX submitted to SAB.

Show at minimum:

- name
- related scene/monitor context where currently available
- state
- progress
- size
- SAB/client indicator
- failure reason
- completed/imported state

Do not attempt to reproduce the entire SABnzbd interface. Advanced queue manipulation remains SABnzbd's responsibility for this iteration.

If current ScarletX cancel/delete controls are tightly coupled to the native downloader, they may be removed or disabled in the first decoupling implementation unless a safe SAB equivalent is already straightforward. Submission, tracking, completion, failure, and import are required; full remote queue administration is not.

## Status and Health

Application health/status must report SAB as the downloader dependency rather than native provider state.

Useful states:

- configured and reachable
- configured but unreachable
- authentication/API failure
- not configured

A SAB outage must not take down the ScarletX web application. Search/library/metadata functions remain available; download grabs fail clearly until SAB connectivity returns.

## Error Handling and Security

- Never log SAB API keys.
- Store SAB API key using the existing encrypted settings mechanism.
- Sanitize SAB URLs before including them in errors if credentials/query secrets could be present.
- Use bounded HTTP timeouts.
- Treat invalid/malformed SAB responses as client errors, not application crashes.
- Preserve idempotency around completion/import so polling the same completed SAB history item repeatedly cannot import a scene repeatedly.
- Avoid deleting SAB history records automatically in the first implementation. ScarletX must not destroy downloader history merely because it imported media.
- A failed connection or API call must preserve the last known ScarletX tracking state and retry on the next polling cycle rather than incorrectly marking downloads failed.

## Upgrade and Compatibility Strategy

Existing 0.3.10 databases may contain:

- native downloader settings
- native provider credentials
- native downloader job/history rows
- tracked download rows that refer to native jobs

Upgrade behavior:

1. Preserve all existing database tables and rows.
2. Stop creating new native jobs after the SAB architecture is active.
3. Do not silently migrate an in-progress native job into SABnzbd; there is no safe one-to-one transfer.
4. Existing in-progress native jobs become historical/legacy state. The UI may label them legacy if they remain visible.
5. Add/preserve SAB settings without destructive migration of unrelated settings.
6. Existing installations must configure SAB before new grabs can be submitted.

The migration must be repeatable and safe if startup is interrupted.

## Testing Strategy

Implementation follows red-green tests.

### Unit tests

- SAB configuration validation
- encrypted API-key persistence
- Test Connection success/auth/network/malformed-response cases
- release submission and returned external ID
- category and priority propagation
- SAB queue state normalization
- SAB history completion/failure normalization
- missing-from-queue but present-in-history behavior
- absent-from-both reconciliation behavior
- batch status retrieval
- sanitization of errors/logging

### Application contract tests

- search/manual grab submits through the neutral downloader facade and never imports `native_usenet`
- monitored automatic search submits through the same facade
- RSS grabs submit through the same facade
- successful SAB completion reaches existing import pipeline once
- repeated polls cannot duplicate an import
- SAB failure does not invoke import
- SAB outage does not crash the app and preserves last-known tracking state
- restart recovery uses persisted external IDs
- download status endpoint/UI exposes normalized ScarletX state rather than raw SAB schema

### Regression tests

- library scanning/import/naming behavior remains unchanged after the handoff point
- 0.3.10 database upgrade preserves native job tables/data
- dormant native modules still import where compatibility tests require them
- existing non-downloader test suite remains green

### Verification

Before claiming completion:

- full supported Python test matrix passes
- Ruff/compile checks pass
- container builds pass
- clean install with SAB configuration is exercised
- upgrade from representative 0.3.10 database is exercised
- mocked SAB contract tests cover queue/history transitions
- a real SABnzbd integration smoke test is run when an integration environment is available; if not available, that limitation must be stated rather than implied away

## Deployment and TrueNAS

ScarletX no longer needs direct Usenet-provider connectivity for normal operation. It needs HTTP(S) connectivity to SABnzbd and normal connectivity to indexers/metadata providers.

TrueNAS documentation/configuration must support:

- SABnzbd URL reachable from the ScarletX container
- shared completed-download dataset/mount
- preferably identical completed path inside both containers
- ScarletX media-library mount as currently required

ScarletX should not automatically assume `localhost` refers to SABnzbd because in container deployments that points back to ScarletX itself.

## Implementation Boundaries

Expected areas of change include:

- `scarletx/download_clients.py`
- new SAB downloader client module/package
- `scarletx/config.py`
- `scarletx/settings_store.py`
- download tracking/polling code
- application routes/status output
- Settings and Downloads frontend surfaces
- startup/runtime worker wiring
- tests for manual/RSS/monitor grabs and import reconciliation
- Docker/TrueNAS documentation/configuration where shared paths are described

Dormant native code should receive only changes required to disconnect it safely or preserve import compatibility. This effort must not turn into a native downloader cleanup project.

## Acceptance Criteria

The refactor is complete when all of the following are true:

1. A ScarletX manual, monitored, or RSS-selected NZB is submitted to SABnzbd rather than the native downloader.
2. Core release-selection code does not import or call native downloader internals.
3. ScarletX persists the SAB external job ID and tracks its state across restarts.
4. Queue/history reconciliation correctly distinguishes active, completed, and failed SAB jobs.
5. A successfully completed SAB job enters ScarletX's existing import/naming/library pipeline exactly once.
6. A failed SAB job never enters the import pipeline and surfaces a useful failure state.
7. SAB unavailability does not prevent ScarletX library/search/metadata use.
8. SAB API credentials are encrypted and never emitted in logs or API responses.
9. Native NNTP provider/settings/runtime worker behavior is absent from the normal product path.
10. Native downloader source and legacy database content remain intact for compatibility/future work.
11. Existing 0.3.10 databases upgrade without destructive loss of native job/settings data except settings explicitly retired from the active UI/runtime.
12. Full regression tests, build checks, and the targeted SAB contract suite are green before merge.
