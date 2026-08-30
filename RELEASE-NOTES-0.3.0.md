# ScarletX 0.3.0

- Adult/XXX studio-scene manager based on the latest SceneCore adult feature set.
- TPDB-verified production studios/sites only. Scenes without a valid TPDB site entity are hidden and rejected.
- Creator/tube/amateur sources are blocked, including OnlyFans, ManyVids, Pornhub, and Anal Vids / AnalVids network.
- Scene views use compact lists with performer/studio links and per-scene Monitor actions.
- Performer and studio profiles include Monitor All; monitoring immediately searches enabled indexers and queues matching downloads.
- Performer cards and images open the performer profile.
- Performer/studio scene lists show ScarletX download state per scene.
- Performer measurements display US units first with metric equivalents in parentheses.
- ScarletX Built-In Usenet is the only download client; SAB, torrent, Movie/TV, and TMDB runtime paths are not included.
- NNTP is TLS-only. Private dev seeds include Astraweb (50 connections) and Newshosting (100 connections).
- Private dev indexer and TPDB credentials are embedded for local testing and masked from settings responses.
- Built-in Usenet settings include a live download speed-limit slider from Unlimited to 250 MB/s.
- Native downloads use the TPDB scene title as the job/completed-folder name.
- Download-client information no longer shows the indexer source.
- Failed native jobs are separated from the active queue, preserved under `downloads/failed`, resumable, and clearable with Clear Failed.
- NNTP scheduling now load-balances across configured providers and keeps a rolling segment window to avoid idle connections.
- yEnc decoding was optimized from a byte-by-byte Python loop to bulk line decoding.
- PAR2, RAR extraction, and 7-Zip are part of the normal macOS/Docker install path.
- Added a Linux Dockerfile and Compose example using persistent `/config`, `/downloads`, `/media`, and `/backups` mounts.
- Added an integrated local media library/player: background scanning, FFprobe metadata, fingerprints, duplicate/missing/unmatched detection, screengrabs/thumbnails, direct browser playback, resume position, play counts, favorites, and lazy preview generation.
- Completed ScarletX downloads are indexed automatically after import.
- TPDB JSON responses and entity artwork are cached persistently to reduce repeated network calls and improve repeat-view responsiveness.
- Monitor now returns immediately after marking the scene monitored and starts indexer search/download work in the background.
- Docker/Linux image now includes FFmpeg/FFprobe in addition to PAR2, RAR extraction, and 7-Zip; `/media` is seeded as the default container scene root.
- Activity download queue now refreshes live every 750 ms without redrawing the table, including percent, downloaded/total bytes, speed, ETA, status, and active-download count.

## Downloader performance update

- Default active NNTP worker cap reduced from 150 to 60; baked Astraweb/Newshosting provider values remain 50/100 hard maxima and are weighted approximately 20/40 during normal transfers.
- Native download progress is maintained in memory for the live queue and persisted to SQLite at most once per second instead of once per completed article.
- SQLite now uses WAL mode, NORMAL synchronous mode, and a busy timeout so live queue reads do not stall download progress writes.
- NNTP BODY data and yEnc decoding stream directly to segment files instead of buffering each entire article in memory.
- NNTP sockets use larger receive buffers and persistent per-worker TLS connections.
- Speed/ETA use a rolling transfer window for more responsive live values.
- Pause/cancel database polling is throttled to avoid per-segment SQLite reads.
- Fresh/local installs use `/tmp` as the default scene root folder unless `SCARLETX_DEFAULT_MEDIA_ROOT` is explicitly set.
- The macOS launcher now finds a usable Python 3.11+ (including Homebrew Python), automatically recreates stale/broken virtual environments, and avoids hard-coded `.venv/bin/python3.x` paths.

## NNTP throughput fix

- Replaced grouped provider scheduling with fair weighted scheduling. With the baked 50/100 provider limits, a 60-worker active window now dispatches about 20 Astraweb and 40 Newshosting tasks instead of the previous 50/10 first-wave bias.
- Replaced thread-local NNTP sessions with bounded shared provider connection pools. ScarletX now reuses TLS sessions across workers and cannot accumulate more open sessions than each provider's configured maximum.
- Provider failover remains enabled for missing/failed articles.

### FIFO download queue
- Active downloads are displayed oldest first.
- ScarletX processes queued jobs from the top down, oldest to newest.
- New downloads are appended to the bottom of the active queue.
