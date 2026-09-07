# Downloader Recovery and Filtering Design

## Goal

Make the built-in downloader recoverable without restarting ScarletX, prevent
undesired small/sample/image releases from entering the usable download path,
stop completed-import failures from returning an opaque HTTP 500, and simplify
the Library media display.

## Scope

This change covers five user-visible behaviors:

1. The Activity page can restart only the built-in downloader worker.
2. ScarletX rejects releases smaller than 500 MiB and rejects release titles
   that identify the release as a sample or image set.
3. The NZB pipeline skips image and sample/trailer payload entries and refuses
   to complete a release when no eligible main video remains.
4. The Library media list and player no longer display filenames or audio codec
   information.
5. The first-run UI opens without account setup or login; optional UI
   authentication can be configured and enabled later from Settings.

The 500 MiB threshold is fixed policy for this change, not a new setting. It is
exactly 524,288,000 bytes.

## Current Failure Analysis

The application creates `native_worker_loop` as an anonymous lifespan task. It
does not retain an independently restartable handle or expose worker health. An
exception outside `process_job` can therefore terminate the task permanently
while the web application continues serving requests. The queue remains visible,
but no job advances until the entire application restarts.

Completed-download processing isolates only `FileImportError` and
`MetadataProviderError`. Other operational failures from filesystem access,
database work, probing/indexing, or webhook delivery can escape the request. The
background import loop silently retries them, while the manual Process Completed
request returns HTTP 500. This combination hides the actionable job error and
makes the worker failure appear broader than it is.

## Worker Supervision and Restart

Add a small in-process downloader supervisor responsible only for the native
downloader task. It owns the task handle, serializes start/restart operations,
tracks the latest failure, and exposes a status snapshot.

At application startup, the supervisor starts the existing native worker loop.
At application shutdown, it cancels and awaits the task using the same cleanup
semantics as the other background tasks.

The supervisor automatically starts a replacement if the worker exits
unexpectedly. It applies a bounded delay before replacement so a persistent
configuration or database error cannot create a tight crash loop. Ordinary job
failures remain handled by `process_job` and do not trigger a worker replacement.

`POST /api/download-client/restart` performs a manual restart. It:

1. serializes concurrent restart requests;
2. cancels and awaits the current native worker task;
3. relies on `process_job` cancellation cleanup to preserve partial data;
4. changes interrupted native jobs in `downloading` or `postprocessing` state to
   `queued`, clears live-only speed/ETA state, and leaves paused jobs paused;
5. starts one fresh worker task; and
6. returns the new worker status and number of re-queued jobs.

`GET /api/download-client/status` extends the existing payload with a worker
object containing `state` (`running`, `restarting`, or `failed`), whether a task
is alive, the latest bounded error message, and the last restart timestamp.

The Activity page adds a Restart Downloader button beside Process Completed.
The button is disabled during the request, asks for confirmation because an
active transfer will be interrupted briefly, then reports how many jobs were
re-queued and refreshes the queue. It does not restart the API, import worker,
search worker, scanner, RSS worker, backup worker, or event stream.

## Release Filtering

Define one release-policy helper shared by automatic selection and manual
specific-release grabs.

A release is rejected before submission when:

- its reported total size is present and below 500 MiB; or
- its title contains a standalone `sample`, `trailer`, or image-set marker.

Image-set markers include standalone `image`, `images`, `photo`, `photos`,
`picture`, `pictures`, `gallery`, or `screenshots`. Matching is token-based so
substrings inside unrelated words do not cause rejection. A missing indexer size
is not rejected at this stage because it is unknown rather than small.

Automatic release selection omits rejected releases. A manual release grab
returns a blocked result with the exact policy reason. The reason is suitable for
display and history/debugging, but no rejected release is enqueued.

After the NZB is fetched, ScarletX validates the advertised sum of all NZB
segments. If that known total is below 500 MiB, the job fails before opening NNTP
connections. This enforces the whole-release threshold even when the indexer size
was absent or inaccurate.

The NZB file classifier treats common image extensions as optional and skips
them. Files whose subject or decoded filename contains a standalone `sample` or
`trailer` token are also skipped. Archive, PAR2, and other files required to
construct the main payload retain their existing scheduling behavior.

After extraction/de-obfuscation, primary-video selection never falls back to a
sample or trailer. If filtering leaves no eligible main video, the job fails with
a clear policy error and remains available in Failed for inspection/retry.

## Completed-Import Failure Isolation

Completed processing handles each completed job independently. Any operational
exception for one job is recorded on that tracked download as `import_pending`
with a bounded error message, emits failed Import status, increments the returned
failure count, and allows later jobs to continue.

The manual Process Completed endpoint returns a normal summary whenever the
request itself and database are reachable. Job-level failures are represented in
`checked`, `imported`, and `failed`; they do not become HTTP 500 responses.
Cancellation and process-level fatal exceptions are not swallowed. Webhook
delivery failures are isolated from durable import completion and must not turn a
successful import into an HTTP 500.

## Library UI

The Media Files table removes the File column. Missing-file state moves into the
Scene cell beneath the studio so the warning remains visible. The Media column
continues showing resolution, video codec, and duration but omits audio codec.

The player Media Information section removes the Audio fact. Backend response
fields remain unchanged for API compatibility; this is a presentation-only
change.

## Optional UI Authentication

Add a persisted `ui_auth_enabled` setting with a default of `false`. The upgrade
default is also `false`, including installations that already contain an
administrator account. Existing accounts and session records are retained so no
credentials are destroyed, but they do not gate ScarletX while the setting is
off.

When UI authentication is disabled, the static application boots immediately,
first-run setup does not create or request a setup token, and ScarletX API calls
made by the UI do not require a session cookie. The independent API-key setting
and credential mechanism remain stored for future integration use, but the
browser UI does not ask for an API key.

The Settings security area adds an Enable UI Authentication control plus
username, password, and confirmation fields. Enabling authentication requires
valid credentials in the same operation. ScarletX creates or updates the single
administrator, creates a session for that administrator, persists the enabled
setting, and keeps the current browser signed in as protection takes effect.

Disabling UI authentication is allowed only from an authenticated session while
the gate is enabled. Disabling preserves the administrator account, revokes old
sessions, and makes subsequent UI visits open directly. Re-enabling later
requires setting credentials again while ScarletX is open.

The legacy token-based first-run setup flow and build-time login gate are removed
from normal boot. Authentication core code remains because Settings can enable
it later. Status responses explicitly report whether UI authentication is
enabled so the frontend can either boot immediately or render the login form.

## Testing

Tests will cover:

- automatic supervisor recovery after an unexpected worker exit;
- manual restart cancellation, re-queuing, paused-job preservation, and exactly
  one replacement task;
- downloader status and restart route contracts;
- release rejection for sizes below 500 MiB, boundary acceptance at 500 MiB,
  token-safe title filtering, and unknown-size behavior;
- NZB advertised-size rejection before segment fetching;
- image/sample entry skipping and rejection when no eligible main video remains;
- per-job completed-import exception isolation and webhook failure isolation;
- Activity restart controls and the absence of filename/audio columns and player
  audio details; and
- open first-run and upgrade behavior, optional enable/disable transitions,
  credential validation, retained accounts, session continuity when enabling,
  and immediate frontend boot while authentication is disabled; and
- the existing downloader, queue-event, progress-persistence, route-contract,
  and UI contract suites.

All behavior changes follow test-driven development: each test is observed
failing for the expected missing behavior before the minimal implementation is
added.
