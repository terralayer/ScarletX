# ScarletX Status Console Design

## Goal

Add a full ASCII/ANSI startup dashboard and structured live status logging that reports the health and activity of ScarletX subsystems without changing the released 0.3.9 version or modifying `main`.

## Release constraint

- Work lives only on `feature/status-console`.
- `main` remains the stable 0.3.9 release.
- `pyproject.toml` and FastAPI version remain 0.3.9 while this branch is under development.
- Future beta/version work is separate from this feature branch.

## Console presentation

At application startup ScarletX prints a large ASCII ScarletX wordmark followed by a grouped status dashboard. ANSI colors are enabled only when stdout is an interactive terminal and color is not disabled. Plain logs receive the same content without escape sequences.

Status semantics:

- `✓` / READY / ONLINE / SECURE / CLEAR / WRITABLE / ENABLED / ENCRYPTED / NON-ROOT: healthy, green.
- `●` / ACTIVE / RUNNING / DOWNLOADING / VERIFYING / PROCESSING: active, cyan.
- `!` / DEGRADED / WARNING / RETRYING / DISABLED: warning, yellow.
- `✗` / FAILED / OFFLINE: error, red.

## Startup groups

### SYSTEM

Report FastAPI/backend readiness, database readiness, database pool capacity, secret-store readiness, authentication readiness, first-run setup state, SSE capability, and the Nginx/public-boundary expectation.

### METADATA

Report ThePornDB configuration readiness, metadata cache readiness, artwork-fetcher security readiness, performer count, studio count, and scene count.

### SEARCH

Report enabled/configured indexer counts, search readiness, monitored scene count, and automation scheduler state.

### USENET

Report native downloader enabled/configured state, each configured provider with SSL/plain transport indication, configured connection count, queue counts, failed count, and configured speed limit/unlimited state.

Startup MUST NOT perform external provider/API calls solely to draw the banner. Network connectivity is reported later by live event logging when a real operation tests or uses the provider.

### POST-PROCESSING

Report PAR2/tool availability, repair/unpack feature states, archive-extraction tooling, archive security, import-worker readiness, and pending completed-download imports.

### LIBRARY

Report scene media roots and path state, incomplete/complete download directories, library scanner, scene matcher/indexing capability, and auto-import worker readiness.

### STORAGE

Report configuration/database/backup paths, encryption-key readiness and permissions, and most recent backup timestamp when available.

### SECURITY

Report runtime UID/non-root state, API query-key blocking, archive traversal protection, remote-artwork network restrictions, HTTP/Nginx hardening capability, and encrypted secret storage capability.

## Live events

Provide a small structured console API that emits aligned lines such as:

```text
[✓] Astraweb ................. CONNECTED
[●] Download ................. 42.6 MB/s | 67%
[●] PAR2 ..................... VERIFYING | 81%
[✓] Import ................... /media/Studio/2026/Scene Name
[!] Newshosting .............. RETRYING | 2/4
[✗] Archive .................. unsafe path blocked
```

The API sanitizes newlines and control characters in labels/detail strings so external metadata cannot forge additional log lines.

## Architecture

Create `scarletx/status_console.py` as a focused presentation/status module. It owns ANSI handling, severity mapping, dashboard rendering, startup snapshot collection, and live event formatting. `scarletx/main.py` invokes it during lifespan startup after database migration/settings loading. Worker modules can call the same `emit_status()` helper for activity/error transitions without knowing about FastAPI.

The module receives the database session and runtime Settings rather than importing the FastAPI app, avoiding circular dependencies.

## Error handling

- Dashboard collection is best-effort; one unavailable subsystem never aborts startup.
- Never render secret values, setup tokens, passwords, API keys, or encryption-key material.
- Paths may be rendered, but credentials embedded in URLs must never be rendered.
- Terminal width differences must not cause exceptions; long details are truncated safely.

## Testing

Add `tests/test_status_console.py` covering ASCII/group rendering, ANSI/no-ANSI behavior, severity symbols/colors, control-character sanitization, secret redaction, best-effort unavailable-path behavior, and unchanged 0.3.9 version metadata. Existing hardening tests and full pytest/compileall remain green.
