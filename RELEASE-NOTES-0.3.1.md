# ScarletX 0.3.1 Local

- Fixed native download Cancel so active NNTP reads are interrupted instead of waiting indefinitely for a segment.
- Cancelled jobs now leave the active queue immediately and partial work files are removed.
- Added a Completed section to Activity with completion/import/post-processing state.
- Added fast paged library APIs for Scenes, Performers, and Studios.
- Replaced the Scenes full-library N+1 query path with bulk queries.
- Dashboard now uses lightweight counts plus only eight recent scenes instead of loading three entire libraries.
- Added client-side library caching and incremental Load more rendering.
- Added composite SQLite indexes and larger read cache/mmap settings for large libraries.
- Calendar now defaults to today through the next 90 days and only shows upcoming monitored release dates.
- Paged the Media Library file list (200 at a time) and added direct per-file detail lookup for playback.
- Batched live Activity queue/tracked-download lookups to avoid N+1 database traffic during the 750 ms refresh loop.
