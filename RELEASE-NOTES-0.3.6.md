# ScarletX 0.3.6 Local

Performance-focused native Usenet release.

## Downloader
- Writes yEnc parts directly into sparse/preallocated target files at their yEnc offsets; no normal `.seg` payload files or second concatenate pass.
- Uses SABCTools SIMD yEnc decoding and native positional file writing when available, with a safe built-in fallback and non-fatal best-effort accelerator installation.
- Feeds the native decoder with large buffered NNTP BODY chunks instead of one Python `readline()` call per yEnc line.
- Runs one global priority queue across NZB payload files instead of completing one file before scheduling the next.
- Starts with a modest connection working set, rapidly autotunes upward while aggregate throughput improves, and backs down when excess concurrency reduces throughput.
- Keeps authenticated NNTP provider pools warm across scenes; cancellation aborts active BODY sockets without permanently closing the shared pool.
- Learns provider throughput and availability separately for fresh, <1-year, 1-3-year, and archive-age posts.
- Continues to spill work to the alternate provider when the current fastest provider is saturated or missing an article.
- Downloads useful video/archive payloads before metadata/support files.
- Defers PAR2 recovery volumes and downloads them only when the primary payload actually requires recovery.
- Healthy direct videos and healthy archive sets can therefore skip unnecessary PAR2 recovery traffic entirely.
- Legacy 0.3.5 fully-downloaded `.seg` sets are migrated without redownloading.

## Post-processing
- Fast-path media detection runs before recovery-volume downloads.
- Existing bounded PAR2/unpack timeouts and cancel support remain in place.

## UI/large libraries
- Retains cursor paging, append rendering, thumbnail caching, FTS5 search, incremental scans, filesystem watching, SSE activity updates, and cached settings from the 0.3.x performance work.
- Background-prefetches the next Scenes/Performers/Studios/Media cursor page so Load More is normally already warm.
- Widens the file-backed SQLite read connection pool while keeping WAL/memory-cache tuning.
