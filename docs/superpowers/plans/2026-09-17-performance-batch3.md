# Performance batch 3 — version locked to 0.4.9

User approved all five candidates. Preserve existing staged work and release lock.

1. Bound outstanding scan-probe futures to twice the worker count; prove peak queued work independently of input size.
2. Offload downloader resume enumeration, finalization, NZB file I/O, filename-marker writes and control/progress database operations. Worker calls own database sessions. Drain filesystem tasks before shutdown cleanup to prevent races with cancellation.
3. Limit scene-list ORM columns to the response fields, including related studio/performer summaries. Verify omitted descriptions are not selected and output remains unchanged.
4. Warm independent artwork through a bounded per-bundle pool, preserving preferred-image order and error accounting. Snapshot ORM inputs before concurrency; no shared Session use by concurrent jobs.
5. Add rebuildable canonical-path cache tables, with indexes for scoped selection. Invalidate changed/deleted DB paths and directories whose resolved path/stat signature changes. Directory changes trigger re-resolution of contained records, including replaced symlink files. First scan backfills; repeated scans inspect directories and changed paths instead of resolving every file.
6. Test failure/cancellation/symlink changes, measure local fixtures, run suite/review/container lifecycle checks, update saved bundle. No publication/version bump.

Implementation and independent review completed. Review corrected cancellation after final commit and moved completion/failure relocation to drained workers. 590 Python tests passed; Ruff and compilation passed. Both synthetic benchmark tools completed. Container lifecycle evidence is recorded separately. Version remains 0.4.9; no publishing.
