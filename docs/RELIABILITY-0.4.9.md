# ScarletX 0.4.9 reliability verification

Version stays locked to 0.4.9. This batch covers backup/restore, interrupted work, large libraries, storage failures and lifecycle validation. It adds no diagnostics export.

## Behavior

- An application shutdown returns an active download to queued state and retains partial data, counters and its unpack password. Paused downloads remain paused. Explicit user cancellation remains cancelled. Startup already resumes queued work and requeues downloads interrupted by abrupt process termination.
- Scan and metadata jobs resume through the existing startup dispatcher. Invalid recovery payloads fail with a visible explanation instead of crashing startup or remaining queued indefinitely.
- Inaccessible scan directories retain existing media/unmatched presence records and scan checkpoints. Scan results record the failed directory and error count. Genuine missing files in accessible directories retain the existing missing-file behavior.
- Download directory creation and retry-directory moves now use the normal durable failure path. Full-disk, permission and read-only errors record a failed, manually retryable job. Existing partial-download paths remain attached if retry setup fails.
- Backup directory errors become actionable backup errors. Failed backup cleanup is best-effort and cannot mask the original storage failure. Previously saved backups are not removed by a failed creation.

## Backup and restore

The application backup is a SQLite database plus its adjacent `.secret.key` file. The matching key is required to decrypt integration credentials and API keys. The database contains settings, library metadata, accounts and sessions. Media files and incomplete downloads are separate persistent datasets and are not included in this database backup.

Automated round-trip checks verify library metadata, application settings, administrator password verification, session validity and decrypted API keys after restoring both files into a separate database/key location. A wrong or missing matching key fails decryption as expected.

Restore while ScarletX is stopped. Preserve the current database/key pair and any WAL/SHM sidecars before replacement. Validate the selected backup using SQLite `PRAGMA integrity_check`. Copy the selected database to the configured database path and its matching secret-key file to the configured key path; prevent stale WAL/SHM sidecars from being reused. Retain the configured UID/GID and restrict the key to mode 0600. Restart and verify login, settings, API authentication and library counts. Test this procedure on disposable data before relying on it for recovery.

The disposable container smoke test performs an offline restore and verifies that a setting changed after backup reverts, while session/API authentication and a fresh password login work. It also checks clean setup and replacement of the previous local candidate using persistent volumes at UID/GID 568 and 1000. This is not a TrueNAS hardware test.

## Large library

`tools/benchmark_large_library.py` seeds a disposable file-backed SQLite database with 50,000 scenes, 25,000 media records and 50,000 history records. It traverses all 500 scene pages, rejects duplicate results, checks bounded ORM retention, searches through FTS5, and exercises initial/deep Wanted pages and quality-cutoff batches. Raw measurements are saved separately. Python traced memory excludes SQLite/native allocations and includes the test's ID set; it is not total process RSS or an application-wide memory guarantee.

## TrueNAS lifecycle checklist — pending hardware

Use a separate test application and disposable datasets; do not restore over the production installation during validation. Record the TrueNAS version, catalog revision, image IDs/digests, configured UID/GID and dataset/mount layout.

1. Install the 0.4.9 candidate with separate config/download/media/backup datasets. Confirm the real-logo setup page, required admin credentials, generated key regeneration and Settings redirect. Verify anonymous API denial and authorized API access.
2. Add fictional library records and disposable media. Change a setting, create a database/key backup, restart the app, and verify persistence and login.
3. Start a scan and a controlled test download. Restart the app during work; verify the scan recovers, download data is retained and a deliberately paused job stays paused. Repeat using forced termination on disposable data to exercise durable checkpoints.
4. Upgrade a copy of the prior installation to the candidate. Verify settings, accounts, integration keys, library counts, partial downloads and index migration. Existing installations with no administrator should require setup.
5. Restore the selected backup/key pair offline on the test installation, following the procedure above. Confirm the saved setting, library count and credentials return. Preserve the pre-restore data until validation completes.
6. On disposable datasets, test a quota-full download destination, denied directory permissions and an unavailable additional mount. Confirm the app reports the error, preserves existing records/partial data and supports retry after storage is repaired. Restore permissions/mounts and repeat the operation.
7. Capture pass/fail results and relevant error text without credentials. Publishing/submission remains pending until these actual TrueNAS checks and release authorization are complete.

Injected storage failures and local rootless-container tests provide local evidence only. Sudden hardware power loss, pool faults and TrueNAS app management remain unverified until run on the target system.

## Local results

579 Python tests passed (634 dependency deprecation warnings). Ruff, compilation and independent review passed. The 50,000-scene fixture traversed 500 pages in 5.13 seconds, with a 10.00 ms median page time, 48.98 ms maximum and 4.92 MiB traced peak Python allocation. These are local synthetic measurements, not TrueNAS performance claims.
