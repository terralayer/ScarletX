# ScarletX 0.3.10-beta.2

This beta focuses on downloader recovery, safer release selection, and a simpler local UI experience.

## Highlights

- Supervised native downloader with automatic recovery and an Activity-page restart action that requeues active work.
- Release filtering that rejects releases below 500 MB and ignores sample, trailer, and image-only content.
- Per-job completed-download error isolation so one failed import does not stop processing the remaining queue.
- UI authentication is disabled by default and can be enabled later from Settings while existing database credentials remain persisted.
- Library views no longer display filename or audio codec details.
- TrueNAS backend, web, and permissions containers use explicit `scarletx-0.3.10-beta.2-*` names.

## Beta note

This prerelease is intended for validation before the final 0.3.10 release.
