# ScarletX 0.3.7

ScarletX 0.3.7 is a privacy, responsiveness, and release-hardening update for self-hosted adult scene management.

## Authentication and privacy
- Adds first-run administrator setup and a single-admin login flow before the ScarletX library and application APIs can be used.
- Stores administrator passwords with Argon2id rather than plaintext or reversible storage.
- Adds opaque server-side browser sessions with HttpOnly, SameSite=Lax cookies and a 30-day lifetime.
- Adds logout and administrator credential rotation; changing credentials revokes older sessions.
- Rate-limits failed logins by client address to reduce brute-force attempts.
- Keeps existing API-key automation support for integrations when API-key protection is enabled.
- Keeps `/api/health` anonymous so Docker and TrueNAS health checks continue to work.
- Protects FastAPI `/docs`, `/redoc`, and `/openapi.json` behind authentication.
- Adds browser security headers and disables caching on authentication/setup responses.
- Adds a ScarletX-styled setup/login/account shell without exposing the application before authentication.

## Responsiveness
- Caps built-in Usenet downloader concurrency using the container's effective CPU quota so download workers do not starve the web/API process on small TrueNAS CPU allocations.
- Preserves explicitly configured lower connection limits and still allows larger hosts to use the configured high connection count.
- Adds regression tests for CPU-limited and unconstrained downloader scheduling.

## Release and TrueNAS hardening
- Makes numeric container versions immutable: `main` remains the rolling image, while `0.3.7` is produced only by the `v0.3.7` Git release tag.
- Adds release-contract tests that keep Python, TrueNAS, release-note, and image versions synchronized.
- Expands TrueNAS validation triggers to application code and dependency metadata changes.
- Runs full anonymous image-pull and TrueNAS deployment/health validation for release tags against the exact released container.
- Updates the test workflow to Node-24-compatible `actions/checkout@v5` and `actions/setup-python@v6` generations.

## Upgrade notes
- Existing ScarletX databases are preserved. The authentication tables are created through the existing startup schema initialization.
- After upgrading, the first browser visit requires creation of the ScarletX administrator account.
- Existing API keys remain available for automation after the administrator setup is complete.
