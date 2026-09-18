# ScarletX 0.4.9

Redesigned all nine Settings pages with responsive sections, clearer controls, and TPDB key instructions. Centered dashboard card captions and removed the Discover shortcut. Prepared TrueNAS catalog packaging with stable service names, standard storage options, and expanded validation.

Fixed web proxy reconnection when the backend restarts with a new IP address. Database backups now use unique names even when created within the same second. Release validation fails on timeout instead of silently accepting an incomplete check.

Added mandatory first-run administrator setup with a generated, regeneratable ScarletX API key and automatic navigation to Settings. Existing installations without an administrator require setup too. Restored browser-session and API-key enforcement. Version remains locked to 0.4.9.

Reduced authentication overhead for signed-in browsers and moved synchronous authentication reads off the event loop. Added 50-row Wanted pagination with bulk selection retained, paused fallback polling in hidden tabs, and bounded expired login-rate-limit state.

Moved artwork disk operations and resizing off the event loop, shared simultaneous artwork requests, and isolated contain/crop thumbnail variants. Reduced partial-scan object loading with legacy path compatibility, added Wanted/history query indexes, and bounded quality-cutoff processing in 200-scene batches.

Hardened restart and storage recovery: active downloads remain resumable during app shutdown, unavailable scan folders preserve file presence, malformed background-job recovery data fails clearly, and storage failures preserve retry paths. Added backup/key restore verification, a 50,000-scene pagination/search benchmark, and a TrueNAS lifecycle test checklist.

Bounded scan-probe submissions, added a rebuildable canonical-path index with directory/symlink invalidation, and reduced scene-list columns. Artwork warming now uses limited concurrency. More downloader disk/database work, including cross-dataset completion moves, runs off the event loop with cancellation-safe draining.

Added storage overview, daily download quiet hours with pause/speed caps, read-only library cleanup previews, guided saved-connection tests and backup reminders. Fixed scheduled backup timestamp handling and rejected indexer capability error responses. All remain part of 0.4.9.
