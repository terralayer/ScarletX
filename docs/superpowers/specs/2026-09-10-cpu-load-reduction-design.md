# ScarletX CPU Load Reduction Design

## Goal
Reduce ScarletX background CPU usage without slowing active downloads, weakening hourly monitored performer/studio discovery, or changing user-visible automation semantics.

## Approved behavior
- Keep monitored performer/studio TPDB discovery on a 60-minute cadence.
- Poll download/import state at 60 seconds while active work exists and back off to 120 seconds while idle.
- Make hourly monitored-entity discovery incremental: remember the most recent successful scan per monitored performer/studio and avoid reprocessing unchanged TPDB scene IDs.
- Search indexers only for scenes that are newly discovered, newly release-ready, or retry-eligible in the monitored-entity cycle.
- Batch database lookups used by automation to avoid repeated per-scene queries where practical.
- Cap concurrent TPDB/indexer work to a small fixed amount so hourly scans do not spike all CPU cores.
- Preserve manual searches, native downloader throughput, existing retry policy, calendar behavior, and monitoring persistence.

## Architecture
Introduce a small durable entity-scan cursor table keyed by entity type + local entity ID. The monitored discovery cycle reads that cursor, processes TPDB results in bounded-concurrency batches, upserts only changed/new scene records, and advances the cursor only after a successful entity scan. The application download-processing loop uses the result of each processing pass to choose an active or idle sleep interval.

The automatic search cycle receives only the scene IDs that need attention from monitored discovery. Existing manual/global automatic search behavior remains unchanged. No new downloader pipeline is introduced.

## Performance verification
Extend the existing 0.3.10 benchmark coverage with CPU-work proxies: number of DB queries/processed rows for an idle download-processing pass and number of scene IDs passed to monitored automatic search on repeated discovery cycles. The second unchanged monitored scan should produce no new search candidates.
