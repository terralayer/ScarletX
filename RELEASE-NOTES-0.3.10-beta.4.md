# ScarletX 0.3.10-beta.4

This beta restores downloader responsiveness during browser playback and adds richer scene rows.

## Highlights

- Media streaming releases its database connection before sending the response body, so open video streams cannot exhaust the API connection pool or stall downloader progress.
- API-key settings are loaded outside the ASGI event-loop thread, keeping health checks and UI requests responsive during temporary database contention.
- Native Usenet settings and provider definitions support a 200-connection ceiling on capable hosts while continuing to respect each provider's configured allowance.
- Scene lists show a compact cached TPDB scene image and TPDB studio logo.
- Every scene row includes a Play button, enabled when a local media file is available and disabled otherwise.
- TrueNAS backend, web, and permissions containers use explicit `scarletx-0.3.10-beta.4-*` names.

## Beta note

This prerelease is intended for validation before the final 0.3.10 release.
