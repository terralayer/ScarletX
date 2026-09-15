# ScarletX Butter-Smooth Reliability Design

## Purpose

Make ScarletX feel consistently fast under a large adult-scene library and remain recoverable under downloader, metadata, filesystem, container, and post-processing failures. This work is incremental on top of the existing 0.4.0 codebase and the completed 0.3.10 performance architecture.

## Global constraints

- Do not change the ScarletX application version from `0.4.0` as part of this roadmap.
- Deliver exactly one pull request per numbered roadmap section. Keep each PR independently reviewable and narrowly scoped to that section.
- Preserve existing user databases, settings, media paths, indexers, TPDB credentials, download state, and TrueNAS storage across upgrades.
- TPDB remains the metadata source. Do not add direct studio/site scraping.
- The built-in ScarletX Usenet downloader remains the download path for this roadmap; do not add or assume SABnzbd.
- Default concurrent scene downloads are 2, dynamically sharing the configured global NNTP connection budget. Default concurrent post-processing is 1.
- No failed/stalled download or processing job may indefinitely block unrelated jobs.
- Existing Nginx/public-web plus private FastAPI backend deployment topology remains supported.
- Existing security boundaries and secret redaction rules remain intact.
- New runtime work must be bounded in memory, CPU, database writes, worker count, queues, and event buffering.
- Every behavior change is test-first and must pass the repository's Python 3.11/3.12/3.13, Ruff, compile, benchmark, dependency-audit, container-build, and applicable TrueNAS gates before merge.

## Delivery model

The roadmap is implemented as 42 ordered PRs. A later PR may depend on an earlier one, but it must not silently bundle another section. Existing behavior that already satisfies a section is characterized first, then the PR strengthens the remaining gap with regression coverage rather than rewriting working code.

The sections are:

1. Instrumentation and performance baseline.
2. Database performance.
3. Lightweight API endpoints.
4. TPDB caching.
5. Image performance.
6. Frontend rendering.
7. Real-time event system.
8. Persistent download state machine.
9. Restart/crash recovery.
10. Concurrent scene downloads.
11. NNTP engine performance.
12. Download scheduling.
13. Stuck-job watchdog.
14. Failure classification.
15. Processing worker separation.
16. Backpressure/resource management.
17. Atomic staged imports.
18. Media validation.
19. Scene matching.
20. Safe rename/move.
21. Cleanup.
22. Processing Queue UI.
23. Wanted / Missing.
24. Quality Profiles.
25. Safe automatic upgrades.
26. Duplicate detection.
27. Incremental library scanner.
28. Library health page.
29. Activity/history.
30. Bulk operations.
31. Performer/studio performance.
32. Search performance.
33. Background task architecture.
34. Backend decomposition.
35. Frontend decomposition.
36. TrueNAS/container reliability.
37. Startup performance.
38. Logging.
39. Testing.
40. Stress testing.
41. Regression benchmarks.
42. Release discipline.

## Performance targets

Targets are guardrails rather than excuses to trade correctness for benchmark numbers:

- Common cached/list API calls should normally complete below 150 ms on representative hardware and data sizes.
- Large lists must use server pagination and bounded browser rendering rather than materializing the full catalog.
- UI queue/progress updates must not force whole-page rerenders or high-frequency SQLite commits.
- Idle background workers must avoid tight polling loops.
- Library scans must skip unchanged files and avoid repeated probing/art generation.
- A slow TPDB request, NNTP provider, corrupt archive, or failed import must not starve unrelated API/UI work.
- Runtime queues, replay buffers, caches, and worker pools must all have explicit limits.

## Downloader and processing model

Downloads and post-processing are separate schedulable resources. The downloader owns durable jobs and transitions them through explicit states. Two scene downloads may run concurrently by default, sharing the global provider connection budget dynamically; the limit is configurable. Post-processing defaults to a single concurrent job and must continue independently from network transfers.

The durable processing lifecycle uses explicit stages where applicable: `queued`, `downloading`, `downloaded`, `verifying`, `extracting`, `probing`, `matching`, `renaming`, `moving`, `writing_metadata`, `cleanup`, `imported`, and `failed`. State transitions must be atomic and restart-safe. Operations must be idempotent or detect already-completed work before repeating it.

A watchdog detects no-progress jobs by stage, applies bounded retries with backoff for transient failures, and quarantines terminal failures. Quarantine removes the bad job from the runnable path without deleting evidence needed for diagnosis or retry.

## Import safety

Downloaded payloads are never treated as library media until validation and processing succeed. Work occurs in incomplete/complete/processing staging areas. Final moves use atomic rename on the same filesystem; cross-filesystem transfers copy to a temporary destination, verify the completed copy, then publish it and only afterward remove the source.

Existing library media is never deleted for an upgrade until the replacement has downloaded, validated, processed, and imported successfully. Ambiguous matching goes to review rather than guessing.

## Data and API efficiency

Database work uses query-specific indexes, short transactions, batch writes, fixed query-count tests, and summary projections for list routes. Large relationships are paged. Counts that are expensive and frequently displayed may be cached or precomputed with correct invalidation.

TPDB follows bounded memory cache -> persistent cache -> network, with request coalescing, endpoint-appropriate TTLs, stale-on-transient-failure behavior, and secret-safe telemetry. Artwork uses local cached renditions and card/profile/full-size variants instead of repeatedly transferring large remote originals.

## Frontend efficiency

The browser keeps one bounded real-time queue/event channel, rejects duplicate/out-of-order events, coalesces progress updates, and falls back safely when the stream fails. Large lists use pagination and/or virtualization. Search input is debounced and expensive detail data is loaded only when needed. Navigation preserves useful view state such as filters and scroll position.

## Operations and observability

ScarletX exposes low-overhead runtime metrics for API latency, database latency/slow queries, queue depth/wait, active work, download throughput, import latency, TPDB latency, memory, CPU, and disk capacity. Logs are structured, bounded, secret-safe, and correlated with job/scene IDs where applicable.

Container startup performs only correctness-critical blocking work. Background maintenance is deferred until the API is healthy. Shutdown drains/cancels workers safely and checkpoints durable state. Health checks remain lightweight and do not depend on remote services.

## Testing and acceptance

Each PR begins with a failing regression/behavior test when runtime behavior changes. Required test classes across the roadmap include state-transition tests, crash/restart recovery, disk-full and permission failures, corrupt/missing-article handling, duplicate submission, import atomicity, matching ambiguity, event-stream overflow/reconnect, large-list query counts, large-library scans, and long-running resource-leak checks.

The existing deterministic performance suite remains a merge guard and is extended as new bottlenecks are addressed. Performance claims must include measured before/after evidence or a regression guard tied to the behavior being optimized.

## Release discipline

This roadmap does not itself define a new ScarletX version. Version and release metadata remain unchanged throughout the 42 PRs unless the user separately requests a release/version operation. PRs are merged in dependency order only after their focused tests and normal repository gates pass.