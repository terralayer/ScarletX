# ScarletX Authentication Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ScarletX private by default with one administrator account, Argon2id password hashing, server-side browser sessions, first-run administrator setup, login rate limiting, logout/password change, and continued API-key automation support.

**Architecture:** Authentication lives in focused `auth.py` and `auth_routes.py` modules rather than growing `main.py`. The database stores one `AuthUser` and opaque-session digests in `AuthSession`; FastAPI middleware accepts either a valid browser session or the existing API key, while the SPA renders setup/login/authenticated states using an HttpOnly cookie.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.x, Pydantic 2.x, pwdlib with Argon2 support, SQLite, pytest/pytest-asyncio, existing single-file HTML/JavaScript SPA.

**Spec:** `docs/superpowers/specs/2026-08-30-authentication-hardening-design.md`

## Global Constraints

- Preserve all existing SQLite application data and existing downloader/media/settings behavior.
- Exactly one administrator account; no multi-user, roles, OAuth/OIDC, Redis, or external auth service.
- Administrator password minimum length is 12 characters and must only be stored as an Argon2id hash.
- Browser sessions are server-side, 30 days, and store only a SHA-256 token digest in SQLite.
- Cookie name is `scarletx_session`, with `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` on HTTPS requests.
- Anonymous access remains allowed only for `/api/health`, `/api/auth/status`, `/api/auth/login`, `/api/setup/status`, and `/api/setup/admin` while setup is required, plus the SPA/static shell.
- Existing ScarletX API-key automation remains accepted when enabled.
- Login rate limit is 5 failed attempts per client address in a rolling 5-minute window.
- Existing Docker and TrueNAS health checks against `/api/health` must continue to work anonymously.
- Existing Python 3.11, 3.12, and 3.13 CI matrix remains required.

---

### Task 1: Authentication persistence and validation schemas

**Files:**
- Modify: `requirements.txt`
- Modify: `pyproject.toml`
- Modify: `scarletx/models.py`
- Modify: `scarletx/schemas.py`
- Create: `tests/test_auth_models.py`

**Interfaces:**
- Produces ORM classes `AuthUser` and `AuthSession`.
- Produces request schemas `AdminSetupWrite`, `LoginWrite`, and `AdminCredentialsWrite`.
- `AuthUser.username_normalized` is the lowercase/trimmed unique lookup key.

- [ ] **Step 1: Add failing model/schema tests**

```python
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scarletx.models import AuthSession, AuthUser
from scarletx.schemas import AdminSetupWrite, LoginWrite


def test_admin_setup_requires_12_character_password():
    with pytest.raises(ValidationError):
        AdminSetupWrite(username="admin", password="short", password_confirm="short")


def test_admin_setup_requires_matching_confirmation():
    with pytest.raises(ValidationError):
        AdminSetupWrite(username="admin", password="correct-horse-1", password_confirm="correct-horse-2")


def test_auth_models_hold_hashes_and_session_digests_only():
    user = AuthUser(username="Admin", username_normalized="admin", password_hash="$argon2id$example")
    session = AuthSession(
        user_id=1,
        token_digest="a" * 64,
        created_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    assert user.password_hash.startswith("$argon2id$")
    assert len(session.token_digest) == 64
```

- [ ] **Step 2: Run the tests and verify red state**

Run: `python -m pytest tests/test_auth_models.py -q`

Expected: import failures for `AuthUser`, `AuthSession`, and auth schemas.

- [ ] **Step 3: Add the password-hashing dependency**

Add to `requirements.txt` and `[project].dependencies` in `pyproject.toml`:

```text
pwdlib[argon2]>=0.2,<1
```

- [ ] **Step 4: Add the ORM models**

Append to `scarletx/models.py`:

```python
class AuthUser(Base):
    __tablename__ = "auth_users"
    __table_args__ = (UniqueConstraint("username_normalized", name="uq_auth_users_username_normalized"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100))
    username_normalized: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
```

- [ ] **Step 5: Add the request schemas**

Append to `scarletx/schemas.py`:

```python
class AdminSetupWrite(BaseModel):
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    password_confirm: str = Field(min_length=12, max_length=1024)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        return self


class LoginWrite(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


class AdminCredentialsWrite(AdminSetupWrite):
    pass
```

Also import `model_validator` from Pydantic.

- [ ] **Step 6: Run the focused tests**

Run: `python -m pytest tests/test_auth_models.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt pyproject.toml scarletx/models.py scarletx/schemas.py tests/test_auth_models.py
git commit -m "Add authentication persistence models"
```

---

### Task 2: Password hashing, opaque sessions, and login limiter

**Files:**
- Create: `scarletx/auth.py`
- Create: `tests/test_auth_core.py`

**Interfaces:**
- Produces `hash_password(password: str) -> str`.
- Produces `verify_password(password: str, encoded_hash: str) -> bool`.
- Produces `create_session(db: Session, user_id: int, now: datetime | None = None) -> str` returning the raw cookie token.
- Produces `session_user(db: Session, token: str, now: datetime | None = None) -> AuthUser | None`.
- Produces `revoke_session(db: Session, token: str) -> None` and `revoke_all_sessions(db: Session, user_id: int) -> None`.
- Produces singleton `login_limiter` with `is_blocked(address)`, `record_failure(address)`, and `clear(address)`.

- [ ] **Step 1: Write failing core tests**

```python
from datetime import UTC, datetime, timedelta

from scarletx.auth import LoginLimiter, create_session, hash_password, session_user, verify_password
from scarletx.models import AuthSession, AuthUser


def test_password_hash_is_argon2_and_verifies():
    encoded = hash_password("correct-horse-battery")
    assert encoded.startswith("$argon2")
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("wrong-password", encoded)


def test_session_database_contains_digest_not_raw_token(db_session):
    user = AuthUser(username="admin", username_normalized="admin", password_hash=hash_password("correct-horse-battery"))
    db_session.add(user)
    db_session.commit()
    token = create_session(db_session, user.id)
    stored = db_session.query(AuthSession).one()
    assert token != stored.token_digest
    assert len(stored.token_digest) == 64
    assert session_user(db_session, token).id == user.id


def test_login_limiter_blocks_sixth_failure():
    limiter = LoginLimiter(max_failures=5, window_seconds=300)
    for _ in range(5):
        limiter.record_failure("192.0.2.10")
    assert limiter.is_blocked("192.0.2.10")
    limiter.clear("192.0.2.10")
    assert not limiter.is_blocked("192.0.2.10")
```

- [ ] **Step 2: Run and verify red state**

Run: `python -m pytest tests/test_auth_core.py -q`

Expected: failure because `scarletx.auth` does not exist.

- [ ] **Step 3: Implement `scarletx/auth.py`**

Use `pwdlib.PasswordHash.recommended()` for Argon2id and SHA-256 for session digests:

```python
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import AuthSession, AuthUser

PASSWORD_HASH = PasswordHash.recommended()
SESSION_DAYS = 30


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    return PASSWORD_HASH.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return PASSWORD_HASH.verify(password, encoded_hash)
    except Exception:
        return False


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user_id: int, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user_id, token_digest=_digest(token), created_at=now, last_seen_at=now, expires_at=now + timedelta(days=SESSION_DAYS)))
    db.commit()
    return token


def session_user(db: Session, token: str, now: datetime | None = None) -> AuthUser | None:
    if not token:
        return None
    now = now or datetime.now(UTC)
    row = db.scalar(select(AuthSession).where(AuthSession.token_digest == _digest(token)).limit(1))
    if row is None:
        return None
    if row.expires_at <= now:
        db.delete(row)
        db.commit()
        return None
    row.last_seen_at = now
    user = db.get(AuthUser, row.user_id)
    db.commit()
    return user


def revoke_session(db: Session, token: str) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_digest == _digest(token)))
        db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.commit()


class LoginLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, address: str, now: float) -> deque[float]:
        events = self._events[address]
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def is_blocked(self, address: str) -> bool:
        with self._lock:
            return len(self._prune(address, time.monotonic())) >= self.max_failures

    def record_failure(self, address: str) -> None:
        with self._lock:
            self._prune(address, time.monotonic()).append(time.monotonic())

    def clear(self, address: str) -> None:
        with self._lock:
            self._events.pop(address, None)


login_limiter = LoginLimiter()
```

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_auth_core.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/auth.py tests/test_auth_core.py
git commit -m "Add password and session authentication core"
```

---

### Task 3: Setup, login, logout, status, and credential-change routes

**Files:**
- Create: `scarletx/auth_routes.py`
- Modify: `scarletx/main.py`
- Create: `tests/test_auth_routes.py`

**Interfaces:**
- `router = APIRouter()` is included by `main.py`.
- Routes: `GET /api/setup/status`, `POST /api/setup/admin`, `GET /api/auth/status`, `POST /api/auth/login`, `POST /api/auth/logout`, `PATCH /api/auth/admin`.
- Responses never include password hash or raw session token.

- [ ] **Step 1: Add failing route tests using an isolated test database and TestClient**

Cover these concrete assertions:

```python
assert client.get("/api/setup/status").json() == {"setup_required": True}
response = client.post("/api/setup/admin", json={"username":"admin","password":"correct-horse-battery","password_confirm":"correct-horse-battery"})
assert response.status_code == 200
assert "scarletx_session=" in response.headers["set-cookie"]
assert client.post("/api/setup/admin", json={"username":"second","password":"another-long-password","password_confirm":"another-long-password"}).status_code == 409
assert client.post("/api/auth/login", json={"username":"admin","password":"wrong-password"}).status_code == 401
assert client.post("/api/auth/logout").status_code == 204
```

Also make five bad login attempts from the same test client and assert the next attempt is `429`.

- [ ] **Step 2: Run and verify red state**

Run: `python -m pytest tests/test_auth_routes.py -q`

Expected: 404s for all new endpoints.

- [ ] **Step 3: Implement `auth_routes.py`**

Implement the router with these rules:

```python
COOKIE_NAME = "scarletx_session"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=30 * 24 * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
```

`POST /api/setup/admin` must check `select(AuthUser.id).limit(1)` before insert, return 409 if found, store normalized username + Argon2 hash, create a session, and set the cookie.

`POST /api/auth/login` must use a generic `Invalid username or password` 401 for either unknown username or bad password, record failures in `login_limiter`, clear failures on success, then issue a new session cookie.

`POST /api/auth/logout` revokes only the supplied session and deletes the cookie.

`PATCH /api/auth/admin` requires a valid session, updates username/password, calls `revoke_all_sessions`, then creates a replacement session for the current browser.

- [ ] **Step 4: Include the router in `main.py`**

Add:

```python
from .auth_routes import router as auth_router
...
app.include_router(auth_router)
```

- [ ] **Step 5: Run focused route tests**

Run: `python -m pytest tests/test_auth_routes.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scarletx/auth_routes.py scarletx/main.py tests/test_auth_routes.py
git commit -m "Add ScarletX admin authentication routes"
```

---

### Task 4: Protect application APIs with session-or-API-key middleware

**Files:**
- Modify: `scarletx/main.py`
- Create: `tests/test_auth_middleware.py`

**Interfaces:**
- Middleware accepts a valid `scarletx_session` cookie or the existing API key.
- Public routes are exactly the routes declared in the design plus SPA/static requests.

- [ ] **Step 1: Write failing middleware tests**

Tests must assert:

```python
assert client.get("/api/health").status_code == 200
assert client.get("/api/settings").status_code == 401
```

After setup/login with the same client:

```python
assert client.get("/api/settings").status_code == 200
```

Enable the existing API key in the test DB and assert:

```python
assert anonymous_client.get("/api/settings", headers={"X-Api-Key": key}).status_code == 200
```

- [ ] **Step 2: Run and verify red state**

Run: `python -m pytest tests/test_auth_middleware.py -q`

Expected: anonymous protected APIs still pass through current API-key-only middleware.

- [ ] **Step 3: Replace the current API-key-only middleware**

In `main.py`, define:

```python
PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/setup/status",
    "/api/setup/admin",
}
```

For every other `/api/*` request:

1. Check `request.cookies.get("scarletx_session")` with `session_user()`.
2. If valid, attach the user id to `request.state.auth_user_id` and continue.
3. Otherwise check existing `X-Api-Key`, `apikey`, or Bearer token logic only when `settings.api_key_enabled` is true.
4. If neither authenticates, return `ORJSONResponse({"detail":"Authentication required"}, status_code=401)`.

Do not bypass protected APIs when no admin exists; setup-required installations must expose only setup/auth/public endpoints.

- [ ] **Step 4: Run middleware and route tests**

Run: `python -m pytest tests/test_auth_middleware.py tests/test_auth_routes.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/main.py tests/test_auth_middleware.py
git commit -m "Protect ScarletX APIs with browser authentication"
```

---

### Task 5: Security response headers

**Files:**
- Modify: `scarletx/main.py`
- Extend: `tests/test_auth_middleware.py`

**Interfaces:**
- Every response receives fixed defensive headers.
- Auth/setup endpoints additionally receive `Cache-Control: no-store`.

- [ ] **Step 1: Add failing header tests**

```python
response = client.get("/api/health")
assert response.headers["x-content-type-options"] == "nosniff"
assert response.headers["referrer-policy"] == "no-referrer"
assert response.headers["x-frame-options"] == "DENY"
assert "camera=()" in response.headers["permissions-policy"]
assert client.get("/api/auth/status").headers["cache-control"] == "no-store"
```

- [ ] **Step 2: Run and verify red state**

Run: `python -m pytest tests/test_auth_middleware.py -q`

Expected: missing-header failures.

- [ ] **Step 3: Add response-header middleware**

After `call_next(request)`, set:

```python
response.headers["X-Content-Type-Options"] = "nosniff"
response.headers["Referrer-Policy"] = "no-referrer"
response.headers["X-Frame-Options"] = "DENY"
response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
if request.url.path.startswith("/api/auth/") or request.url.path.startswith("/api/setup/"):
    response.headers["Cache-Control"] = "no-store"
```

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_auth_middleware.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scarletx/main.py tests/test_auth_middleware.py
git commit -m "Add ScarletX authentication security headers"
```

---

### Task 6: Setup/login UI and authenticated request handling

**Files:**
- Modify: `scarletx/web/index.html`
- Create: `tests/test_auth_ui.py`

**Interfaces:**
- SPA boot sequence calls `/api/auth/status` before loading protected application data.
- Auth state values: `setup`, `login`, `authenticated`.
- No password/session/API credential is persisted in browser storage.

- [ ] **Step 1: Add static UI regression tests**

Read `scarletx/web/index.html` and assert it contains:

```python
assert 'id="authGate"' in html
assert 'id="setupForm"' in html
assert 'id="loginForm"' in html
assert 'logoutScarletX' in html
assert '/api/auth/status' in html
assert '/api/setup/admin' in html
assert '/api/auth/login' in html
assert 'localStorage.setItem("scarletx' not in html
assert 'sessionStorage.setItem("scarletx' not in html
```

- [ ] **Step 2: Run and verify red state**

Run: `python -m pytest tests/test_auth_ui.py -q`

Expected: missing auth UI markers.

- [ ] **Step 3: Add auth gate markup and styling**

Add a full-viewport dark-scarlet gate containing:

```html
<div id="authGate" class="auth-gate" hidden>
  <section id="setupPane" class="auth-card" hidden>
    <h1><b>Scarlet</b>X Setup</h1>
    <form id="setupForm">
      <input id="setupUsername" autocomplete="username" value="admin" required>
      <input id="setupPassword" type="password" autocomplete="new-password" minlength="12" required>
      <input id="setupPasswordConfirm" type="password" autocomplete="new-password" minlength="12" required>
      <button class="btn primary" type="submit">Create Administrator</button>
    </form>
  </section>
  <section id="loginPane" class="auth-card" hidden>
    <h1><b>Scarlet</b>X</h1>
    <form id="loginForm">
      <input id="loginUsername" autocomplete="username" required>
      <input id="loginPassword" type="password" autocomplete="current-password" required>
      <button class="btn primary" type="submit">Sign In</button>
    </form>
  </section>
</div>
```

Hide the normal `.shell` until authentication succeeds.

- [ ] **Step 4: Add boot/auth JavaScript**

Implement:

```javascript
async function authStatus(){
  const response = await fetch('/api/auth/status', {cache:'no-store'});
  if(!response.ok) throw new Error('Unable to determine authentication status');
  return response.json();
}

async function bootAuthentication(){
  const status = await authStatus();
  if(status.setup_required){ showAuthState('setup'); return false; }
  if(!status.authenticated){ showAuthState('login'); return false; }
  showAuthState('authenticated');
  return true;
}
```

Setup/login forms POST JSON with `credentials:'same-origin'`; successful responses call `showAuthState('authenticated')` and then the existing application bootstrap/load functions.

Wrap the existing common API-fetch helper, or introduce one if calls are direct, so any protected request returning 401 calls `showAuthState('login')` and throws an authentication error instead of rendering stale/private data.

Add:

```javascript
async function logoutScarletX(){
  await fetch('/api/auth/logout', {method:'POST', credentials:'same-origin'});
  showAuthState('login');
}
```

Wire Logout into the sidebar footer or Settings security section.

- [ ] **Step 5: Run UI regression tests**

Run: `python -m pytest tests/test_auth_ui.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scarletx/web/index.html tests/test_auth_ui.py
git commit -m "Add ScarletX setup and login interface"
```

---

### Task 7: Full authentication regression, compilation, and container compatibility

**Files:**
- Modify if needed after failures: authentication files from Tasks 1-6 only.
- Test: all `tests/`.

**Interfaces:**
- This task produces the review-ready auth branch.

- [ ] **Step 1: Run the complete Python test suite**

Run: `python -m pytest -q`

Expected: zero failures.

- [ ] **Step 2: Verify source compilation**

Run: `python -m compileall -q scarletx tests`

Expected: exit code 0.

- [ ] **Step 3: Verify no secrets are persisted by the new auth tests**

Add/retain a test that creates an administrator and session, then queries SQLite and asserts:

```python
assert plaintext_password not in user.password_hash
assert raw_session_token != session.token_digest
assert len(session.token_digest) == 64
```

Run: `python -m pytest tests/test_auth_core.py tests/test_auth_routes.py -q`

Expected: PASS.

- [ ] **Step 4: Verify health-check compatibility**

Run an application TestClient without any admin/session and assert:

```python
response = client.get('/api/health')
assert response.status_code == 200
assert response.json()['app'] == 'ScarletX'
```

This protects the existing Docker/TrueNAS health contract.

- [ ] **Step 5: Push the branch and let GitHub run the Python 3.11/3.12/3.13 matrix**

Expected: every matrix job completes successfully.

- [ ] **Step 6: Open a pull request to `main`**

Title: `Add ScarletX administrator authentication`

Body must summarize setup/login/session behavior, API-key compatibility, security headers, tests, and note that release/versioning hardening is the next stage.

- [ ] **Step 7: Do not merge until fresh CI is green**

Verify the exact PR head SHA has passing Python 3.11, 3.12, and 3.13 test jobs and source compilation before merging.
