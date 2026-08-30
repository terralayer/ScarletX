# ScarletX 0.3.5 Local

## NNTP hotfix

- Fixes `BODY failed: .` on persistent Astraweb/Newshosting connections.
- Fully drains each NNTP multiline BODY response through its terminating dot after the yEnc `=yend` line before returning a connection to the pool.
- Adds an explicit stream-desynchronization diagnostic if a stale dot response is ever encountered again.
- Keeps the adaptive multi-provider downloader, retry rotation, obfuscated-post recovery, reprocessing, and automatic scene import from 0.3.3.
- Distribution package excludes runtime database/backups, caches, partial downloads, and Python bytecode.
