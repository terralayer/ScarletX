# ScarletX 0.3.3 Local

## Download correctness and speed
- Recovers original filenames from obfuscated PAR2 FileDesc metadata and identifies hash-named PAR2/RAR/7z/ZIP/video payloads by content signature.
- Refuses to mark a job complete until a playable scene video is present.
- Completed downloads awaiting import have a Reprocess action so older hash-named payloads can be repaired in place without re-downloading.
- Provider selection now learns per-provider throughput/reliability and spills immediately to another provider when the fastest pool is saturated.
- Missing articles rotate providers immediately. Transient retry budget is global rather than multiplied per provider; legacy retry values above 2 are migrated to 2.
- Active NNTP sockets are aborted on Cancel and cancelled partial payloads are cleaned up.
- Native ScarletX downloads always import the selected primary video into the configured scene library, even when the legacy external-client File Management toggle is off; support/hash payload directories are removed after a successful move.
- Failed NNTP connection creation now releases its provider pool slot immediately so transient TLS/auth/connect failures cannot silently exhaust the pool and throttle later retries.

## Large-library/UI performance
- Cursor/keyset pagination for scenes, performers, studios, and media files.
- Load More appends only new DOM rows/cards; off-screen cards/rows use content-visibility to avoid unnecessary rendering.
- Persistent local WebP card thumbnails for performer/studio artwork; existing library pages use saved artwork URLs before contacting TPDB.
- SQLite FTS5 indexes for local scene/performer/studio search with LIKE fallback.
- Incremental media scanning skips unchanged files and probes changed/new media with a bounded worker pool.
- Filesystem watcher indexes normal media changes without requiring a full scan.
- Settings are cached in memory, SQLite uses WAL/read cache/mmap tuning, and common library/calendar indexes are created automatically.
- Persistent HTTP connection pools are reused for TPDB, Newznab indexers, and artwork.
- ORJSON responses and GZip compression reduce API serialization/transfer overhead.
- Activity uses Server-Sent Events with polling fallback; background badge polling is reduced.
- System status is briefly cached to avoid repeating count queries during UI startup.

## Calendar
- Calendar defaults to monitored upcoming releases from today through the next 90 days rather than download history.
