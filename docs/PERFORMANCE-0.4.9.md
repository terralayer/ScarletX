# ScarletX 0.4.9 performance verification

Both approved performance batches are implemented. Version remains locked to 0.4.9; nothing published.

- Authentication opens/uses/closes its synchronous database session in a worker thread. A valid browser session uses one query and skips all settings loading. Session authorization is not cached; integration keys read fresh settings.
- Wanted uses bounded SQL limit/offset with a deterministic ID tie-break. Both the base view and shipped bulk-actions override render 50 rows, with a 51st result used only to determine whether Next is available. Bulk selections remain limited to 25 on the current page; stale navigation responses cannot replace the new page. Existing list API callers retain their response format.
- Hidden tabs cancel fallback polling. Visible tabs resync when fallback is still needed. A completing request cannot restart polling after the live stream recovers.
- Login rate-limit lookups do not allocate empty records. Periodic cleanup expires idle records; at most 10,000 addresses and five failure timestamps per address are retained by default. At capacity, new addresses are temporarily blocked instead of evicting existing blocks.

## Local benchmark

160 authenticated requests, concurrency 8, file-backed SQLite, same machine and ASGI harness. One before/after sample for each scenario. No network, nginx, downloading workload or TrueNAS hardware involved. The slow-read case deliberately injects 5 ms per database query; it is not a measurement of the user's disk.

| Scenario | Measure | Before | After |
| --- | --- | ---: | ---: |
| No artificial delay | SQL queries | 320 | 160 |
| No artificial delay | Settings loads | 160 | 0 |
| No artificial delay | Request p95 (ms) | 7.21 | 16.97 |
| No artificial delay | Maximum event-loop delay (ms) | 13.25 | 14.43 |
| No artificial delay | Requests/second | 1003.1 | 710.0 |
| 5 ms simulated delay/query | SQL queries | 320 | 160 |
| 5 ms simulated delay/query | Settings loads | 160 | 0 |
| 5 ms simulated delay/query | Request p95 (ms) | 93.69 | 15.77 |
| 5 ms simulated delay/query | Maximum event-loop delay (ms) | 97.22 | 3.8 |
| 5 ms simulated delay/query | Requests/second | 84.8 | 655.8 |

The slow-read case improved substantially. The no-delay microbenchmark is slower because worker dispatch costs more than its tiny local query workload. This tradeoff keeps real synchronous database stalls off the event loop; no universal speedup is claimed.

## Verification

590 Python tests passed, including session revocation, key rotation, slow-read responsiveness, bounded rate limiting and Wanted pagination. Browser checks passed for dashboard, Settings, initial setup, Wanted/bulk navigation, hidden tabs and stream-recovery races. Ruff, Python compilation and JavaScript syntax checks passed. Independent review found the older Wanted override; that was fixed and rechecked.

Candidate container verification is recorded separately in evidence/container-smoke-results.json. TrueNAS clean-install/upgrade testing remains outstanding.

## Artwork, scans and database queries

- Artwork disk reads/writes and Pillow processing run on a dedicated four-worker pool. Concurrent requests for the same artwork share in-progress downloads and resizes. Cancelling one waiter does not cancel the shared work; failures are retryable. Atomic writes use unique temporary files.
- Thumbnail cache keys distinguish contain/crop variants. Existing original images remain cached; thumbnails rebuild once under the new keys.
- Partial scans stream only IDs and paths in batches of 500 to preserve legacy relative paths and arbitrary symlink aliases. Only records inside the selected roots are hydrated, including probes and unmatched files. This still traverses all stored path strings; it does not claim constant-time partial scans. The regression fixture hydrates one media/probe pair instead of 201. Scene matching loads only IDs/titles/dates, lazily when an unknown file needs matching.
- Three composite indexes cover Wanted ordering, per-scene search history, and latest tracked-download lookup. Startup adds them idempotently after the existing migration backup check. Partial legacy schemas are handled without referencing missing columns.
- Quality-cutoff checks use 200-scene batches, project only needed file fields, and stop at the requested result limit. Cross-batch ordering, best-file quality, custom profiles and empty libraries are covered.

### Synthetic measurements

Same local machine and deterministic fixtures; these are not measurements of TrueNAS hardware or a user's library.

| Workload | Before | After |
| --- | ---: | ---: |
| 20 concurrent requests for one thumbnail: downloads/resizes | 20 / 20 | 1 / 1 |
| Artwork burst elapsed time | 555.91 ms | 74.75 ms |
| Maximum event-loop delay during burst | 534.4 ms | 1.4 ms |
| Wanted query median, 5 runs | 277.48 ms | 1.04 ms |

Artwork uses a deterministic 1600×900 JPEG, 320×180 thumbnail and simulated 20 ms network delay. Wanted uses file-backed SQLite with 1,000 scenes, 5,000 history rows and 5,000 tracked downloads, fetching 51 rows. Its query plan uses all three new indexes without temporary sorting. Raw JSON evidence and repeatable benchmark tools are included in the preparation bundle/source patch.

Independent review found a symlink-alias scope regression; canonical path filtering and regression coverage address it. Full Python and browser checks cover both batches. Actual TrueNAS installation/upgrade testing remains outstanding.

Local candidate-to-candidate upgrades passed at UID 568 and 1000 using the same disposable volumes. Settings, browser sessions, API-key access and all three indexes survived container replacement. Storage writes, backups and outbound TLS also passed.

## Third performance batch

- Probe execution retains at most twice the worker count in outstanding futures (four at two workers), rather than queuing every changed file. The scan still retains selected metadata and pending file identities; this does not make the entire scan constant-memory.
- Downloader workspace setup, resume-marker enumeration, saved NZB reads/writes/parsing, file finalization, marker writes, control/checkpoint database calls and completion/failure relocation run in worker threads. Blocking calls own their sessions. Cancellation drains in-flight work before cleanup; a completed job keeps its final path even when shutdown overlaps its final commit.
- Scene summaries select only displayed fields and pagination keys, including limited studio/performer columns. Description text is no longer selected for these lists. Response shape is unchanged.
- Artwork warming uses at most four tasks per phase per scene bundle. Preferred scene/studio image ordering and error counts remain deterministic; ORM input is captured before parallel work, and cancellation drains sibling tasks.
- Rebuildable canonical-path tables cover media and unmatched files. Initial backfill resolves existing paths. Repeated scans check directory signatures and individual file aliases, invalidate changed/deleted database paths, and use indexed canonical ranges to select records. Directory replacement, retargeted directory symlinks and replaced file symlinks are covered. Cache writes commit before filesystem scanning. Source media paths remain authoritative and are not rewritten.

### Local comparison

| Workload | Previous/serial reference | Updated |
| --- | ---: | ---: |
| Scope lookup, 10,000 paths across 20 directories | 98.92 ms | 8.65 ms warm |
| Path resolutions in that warm lookup | 10,000 | 20 |
| Initial path-cache backfill | — | 717.95 ms |
| 16-performer artwork bundle, simulated 10 ms/image operation | 329.96 ms serial | 85.29 ms, four workers |
| Event-loop delay from simulated 50 ms storage work | 50.25 ms | 0.97 ms |
| Outstanding probe futures for 10,000 files | 10,000 | At most 4 |

These are synthetic local samples. The path-cache comparison includes indexed record hydration in the updated case; the old reference resolves ID/path rows. Rebuilding the cache adds initial work and database space. Ongoing validation scales with stored directories and file aliases, while SQL still checks for changed source records.

The 50,000-scene traversal remained correct across 500 pages. Median page time was 11.08 ms versus the earlier 10.00 ms sample; traced Python peak was 4.85 MiB versus 4.92 MiB. This fixture does not demonstrate a list-latency gain. Narrower SQL avoids unused descriptions, verified by regression coverage; timings vary and Python memory excludes SQLite/native allocations.

Reproduce with `tools/benchmark_performance_batch3.py` and `tools/benchmark_large_library.py`. Raw JSON is included with the preparation evidence. Version remains 0.4.9.

Final verification: 590 Python tests passed (688 dependency warnings). Rootless candidate replacement, canonical-cache population, backup/key restore and authentication checks passed at UID 568 and 1000. Actual TrueNAS testing remains pending.
