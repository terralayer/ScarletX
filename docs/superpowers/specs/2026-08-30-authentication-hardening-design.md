# ScarletX Authentication and Privacy Hardening Design

## Goal

Make a new or existing ScarletX installation private by default with a simple single-administrator login, secure browser sessions, retained API-key automation support, and a first-run administrator setup flow. This is the first hardening stage before release/versioning, migrations/secrets, and worker isolation.

## Scope

This stage implements authentication and the minimum first-run setup needed to establish the administrator account. It does **not** introduce multi-user accounts, roles, OAuth/OIDC, external identity providers, Redis, or a separate authentication service. Those are intentionally out of scope.

Existing TPDB, Usenet, indexer, library, automation, and downloader settings remain unchanged in this stage. The later full setup wizard will extend the same setup framework.

## User Model

ScarletX has exactly one administrator account.

- Default username presented during setup: `admin`.
- Username is editable during setup and stored case-insensitively for uniqueness.
- Password minimum length: 12 characters.
- Passwords are stored only as Argon2id hashes.
- No plaintext or reversible password storage.
- The administrator can change username/password after login.
- Changing the password invalidates all existing browser sessions.

A new `AuthUser` table stores the single administrator record. Application startup must never create a default password.

## First-Run Behavior

On startup, ScarletX checks whether an administrator exists.

If no administrator exists:

1. The SPA loads in setup mode.
2. Normal application API endpoints remain unavailable.
3. `GET /api/setup/status` reports `setup_required: true`.
4. `POST /api/setup/admin` accepts username, password, and password confirmation.
5. Successful setup creates the administrator, creates a browser session, and returns the user to the normal ScarletX UI.

The admin-creation endpoint is permanently disabled after an administrator exists. It must return `409 Conflict` rather than allowing a second account to be created.

Existing ScarletX installations upgrade into this same setup-required state once until an administrator is created. Existing media, settings, downloads, and metadata remain untouched.

## Browser Sessions

Browser authentication uses opaque server-side sessions rather than JWTs.

- Login generates at least 32 cryptographically random bytes using Python `secrets`.
- Only a SHA-256 digest of the session token is stored in SQLite.
- Raw session token exists only in the browser cookie.
- Cookie name: `scarletx_session`.
- Cookie attributes: `HttpOnly`, `SameSite=Lax`, `Path=/`.
- `Secure` is enabled when ScarletX sees an HTTPS request.
- Session lifetime: 30 days.
- Session expiry is stored server-side and checked on every authenticated request.
- Logout deletes the current session from the database and expires the cookie.
- Expired sessions are rejected and opportunistically deleted.
- Password changes delete every existing session and issue a fresh session to the current browser.

A new `AuthSession` table stores session digest, administrator id, creation time, last-seen time, and expiry time.

## Request Authentication Rules

ScarletX becomes private by default after this change.

The following endpoints remain unauthenticated:

- `GET /api/health`
- `GET /api/auth/status`
- `POST /api/auth/login`
- `GET /api/setup/status`
- `POST /api/setup/admin` only while setup is required
- the SPA shell and static assets needed to render login/setup screens

All other `/api/*` endpoints require either:

1. a valid browser session, or
2. the existing ScarletX API key when API-key access is enabled.

Requests without valid authentication return `401` JSON for API routes. The SPA handles that response by showing the login screen rather than exposing application data.

The existing `/api/settings/security` API-key feature remains supported for automation and scripts. Browser login does not depend on the API-key setting.

## Login Rate Limiting

Failed login attempts are rate-limited per client address to slow brute-force attacks without adding external infrastructure.

- Maximum 5 failed attempts in a rolling 5-minute window.
- A blocked client receives `429 Too Many Requests`.
- Successful login clears the failure history for that address.
- The limiter stores no passwords, usernames, or secrets.
- Because ScarletX is currently a single web process, an in-process limiter is acceptable for this stage. Worker isolation later must keep the web process as the only login endpoint.

Authentication failures use a generic `Invalid username or password` response so callers cannot enumerate the administrator username.

## Password Hashing

Add a narrowly scoped password-hashing dependency supporting Argon2id. The authentication module owns hashing and verification so the rest of the application does not depend directly on the hashing library.

Interface:

```python
hash_password(password: str) -> str
verify_password(password: str, encoded_hash: str) -> bool
```

Hash verification must support rehash detection so password parameters can be strengthened later without changing the database schema.

## Backend Structure

Authentication logic must not be added directly to the already-large `scarletx/main.py` beyond route wiring and middleware registration.

Create focused modules:

- `scarletx/auth.py` — password hashing, session creation/validation/revocation, login rate limiter, authentication helpers.
- `scarletx/auth_routes.py` — setup, login, logout, status, and credential-change FastAPI router.
- `scarletx/models.py` — `AuthUser` and `AuthSession` ORM models only.
- `scarletx/schemas.py` — authentication/setup request schemas only.
- `scarletx/main.py` — include the router and replace the current API-key-only middleware with combined session/API-key authorization.

The database remains SQLite and continues using the current SQLAlchemy session factory.

## Frontend Behavior

The existing single-page ScarletX UI gains three states:

1. **Setup required** — administrator creation form.
2. **Authentication required** — login form.
3. **Authenticated** — existing ScarletX interface.

The login/setup view uses the existing dark scarlet visual language and does not add a separate theme.

Startup flow:

1. Call `/api/auth/status`.
2. If `setup_required`, show administrator setup.
3. Else if not authenticated, show login.
4. Else load the existing dashboard/application data.

If any application API call later returns `401`, clear authenticated UI state and return to login.

Add a Logout action to the application chrome/settings area.

No credentials are stored in `localStorage` or `sessionStorage`; the browser relies on the HttpOnly session cookie.

## Security Headers

Add lightweight HTTP security headers to all responses:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Frame-Options: DENY`
- `Permissions-Policy` disabling camera, microphone, and geolocation
- `Cache-Control: no-store` for authentication/setup responses

A strict Content-Security-Policy is deferred until the current single-file SPA inline scripts/styles are separated enough to deploy one without breaking the application.

## Error Handling

- Invalid credentials: `401` with generic message.
- Missing authentication on protected API: `401`.
- Setup attempted after admin exists: `409`.
- Password confirmation mismatch: validation error.
- Password shorter than 12 characters: validation error.
- Login-rate limit exceeded: `429`.
- Expired/invalid session: treat as unauthenticated and expire cookie.

Authentication failures must never be logged with submitted passwords, session tokens, API keys, or provider credentials.

## Tests

Add dedicated tests covering:

- first-run setup requirement;
- admin creation and automatic login;
- prevention of a second admin;
- Argon2 password hashing/verification;
- wrong-password and wrong-username behavior;
- login rate limiting and reset after successful login;
- valid/expired/revoked session behavior;
- logout;
- password change and session invalidation;
- protected API rejects anonymous callers;
- protected API accepts a browser session;
- existing API-key access still works when enabled;
- `/api/health` remains anonymous for Docker/TrueNAS health checks;
- SPA auth status transitions;
- no raw password or session token is persisted.

The existing Python 3.11, 3.12, and 3.13 CI matrix remains required.

## Upgrade and Deployment Compatibility

This stage must preserve:

- existing SQLite databases and all current application data;
- TrueNAS non-root UID/GID operation;
- `/config` persistence;
- Docker and TrueNAS health checks against `/api/health`;
- the existing optional API-key automation behavior;
- current default TrueNAS network port behavior.

`Base.metadata.create_all()` may create the new authentication tables in this stage. The later database-migration stage will establish Alembic as the authoritative schema migration system and baseline these tables along with the existing ScarletX schema.

## Follow-On Stages

After authentication is merged and verified:

1. Release/CI hardening and immutable ScarletX `0.3.7` release; update TrueNAS PR #5698.
2. Complete first-run provider/library setup and remove production `DEV_*` seeding.
3. Alembic migrations, pre-migration backup, and application-level credential encryption.
4. Web/worker process isolation, richer readiness checks, SBOM/vulnerability scanning, and expanded operational hardening.
