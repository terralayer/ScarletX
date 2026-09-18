# Artwork, scans and query performance — 0.4.9

User approved all five candidates; retain staged work and locked version 0.4.9.

1. Test artwork burst coalescing, cancellation/error cleanup, disk/resize work off the event loop, and distinct contain/crop cache keys. Offload filesystem/Pillow work to a bounded worker pool; share only in-progress jobs, with unique atomic cache writes.
2. Test partial-scan ORM loads and out-of-scope data preservation. Scope media/probes/unmatched records to selected roots, keep legacy relative path compatibility, and build a lightweight global matching index only when an unknown file actually needs matching.
3. Inspect Wanted query plans and add measured composite indexes to model metadata and existing-database startup migration; verify idempotence and unchanged records.
4. Test quality-cutoff results across batch boundaries and custom profiles. Iterate scenes/files/configs in bounded batches and stop at the requested result limit.
5. Benchmark local artwork bursts/query plans and record limits, then run full Python/browser checks, review, container smoke and update the saved preparation bundle. No version bump or publication.

Completed: 565 Python tests, browser suite, lint/compile, independent review, synthetic benchmarks, and rootless container upgrade checks passed. Review corrected alias filtering: scan scope now streams IDs/paths before hydration to preserve canonical equivalence. Version remains 0.4.9. TrueNAS hardware checks and publishing remain pending.
