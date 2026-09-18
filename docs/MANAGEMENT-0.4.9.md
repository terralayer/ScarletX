# Management features — ScarletX 0.4.9

Version remains locked to 0.4.9. These changes are prepared locally, not published.

## Storage overview

Settings → System shows download folders, media roots, backups and artwork cache. Filesystem capacity is separate from folder size; folders on the same filesystem share free space and must not be added together. Folder measurements are bounded and show partial or unavailable results explicitly. Refresh runs on demand. Folder sizes are apparent file sizes, not unique physical disk usage.

## Download schedule

Settings → Download Client has a separate Save schedule button. Daily quiet hours can pause transfers or apply a speed cap in MiB/s, using an explicit IANA timezone. Overnight periods and daylight-saving timezone conversion are supported. The schedule defaults to disabled and persists across restarts without a database schema change.

Queued jobs wait during scheduled pauses. Active transfers resume automatically when quiet hours end; manually paused jobs remain paused. In-flight articles and post-processing may finish. A scheduled cap never increases a lower global speed limit. This is a daily rule, not a per-weekday calendar.

## Library cleanup preview

Library → Review library lists potential duplicates, missing files and unmatched files in bounded pages. This is read-only and never deletes files or records. Potential duplicates use existing partial fingerprints, so review them before treating them as identical.

## Guided connection setup

Settings provides TPDB, indexer and Usenet steps that link to the existing credential forms. Save credentials there, then click Test saved connection. Success is tied to the tested settings revision; changed settings require another test. Failed retests clear earlier success. Tests run only on request, and failures do not echo provider credentials.

## Backup reminders

Settings → Backups shows the last successful backup and next due time. Dashboard reminders appear for never-created, overdue or missing backups. Disabling automatic backups suppresses the reminder. Keep each database backup and its matching installation key together for restore. File presence is checked; this reminder does not perform a full integrity audit.

## Validation

Focused tests cover scheduling, persistence, manual pauses, backup timestamps, bounded read-only previews, secret redaction and HTTP-200 indexer error responses. Browser checks cover desktop/mobile layouts, connection revision changes, failed retests, schedule save failures and cleanup navigation. Local container lifecycle checks are recorded in evidence. Actual TrueNAS and live-provider throughput testing remain pending.
