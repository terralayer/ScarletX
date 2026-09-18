# Management features — remain on 0.4.9

User approved storage overview, download schedules, cleanup preview, connection setup wizard and backup reminders. No version change or publication.

- Add an authenticated operations router, shared service helpers and focused tests. Storage reports filesystem capacity separately from bounded folder usage, with partial/unavailable labels. Backup reminders distinguish never, overdue, missing, healthy and disabled; no external notifications.
- Persist a validated daily quiet-hours rule (IANA timezone, start/end, pause or capped MiB/s). Default disabled. Apply to queue starts and active transfers; manual pauses never auto-resume. Settings edits take effect without restarting a download. Avoid a schema migration by using existing AppSetting storage.
- Provide bounded, read-only cleanup pages for potential duplicates, missing records and unmatched files. Never delete files or records from preview. Potential duplicates use existing partial fingerprints, clearly labeled for review.
- Add a guided three-step connection panel linked to existing credential forms. Test saved TPDB/indexer/provider settings on explicit clicks. Track test results only for the configuration revision tested; show failures without secrets.
- Integrate panels into existing Settings/Library layout and add a dashboard backup reminder. Keep independent forms from swallowing existing save controls. Test desktop/mobile layout, save failures, navigation races and wizard progress.
- Run Python/browser/review and rootless lifecycle checks, create screenshots and update the saved preparation bundle. Preserve all prior staged changes and the active 0.4.9 lock.

Completed: all five features, focused regressions, 601-test Python suite, browser checks, independent review and local UID 568/1000 upgrade/restore checks. Actual TrueNAS/provider testing remains pending. Version unchanged.
