# ScarletX Nginx Frontend/Backend Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Nginx the only public ScarletX HTTP entrypoint, serving the static UI and proxying protected backend traffic to an internal FastAPI service.

**Architecture:** Keep the current frontend behavior but make it a static artifact. FastAPI becomes backend-only on internal port 8000. Nginx serves frontend files on port 8690 and proxies `/api/*`, `/docs`, `/redoc`, and `/openapi.json` to the backend. Docker and TrueNAS run web and backend as separate containers; only web publishes a port.

**Tech Stack:** Nginx, Docker/Compose, TrueNAS Community Apps templates, Python 3.11+, FastAPI/Uvicorn, pytest, existing vanilla HTML/CSS/JavaScript UI.

**Spec:** `docs/superpowers/specs/2026-08-31-nginx-frontend-backend-separation-design.md`

## Global Constraints

- Nginx is the only public HTTP entrypoint in Docker/TrueNAS deployment.
- Backend listens on internal `0.0.0.0:8000` and publishes no host port.
- Web listens on `8690` inside its container and owns the published host/TrueNAS port.
- Existing `/api/*` URLs and `/api/health` response contract remain unchanged.
- Existing browser-session and API-key authentication remain unchanged.
- `/api/activity/stream` must remain unbuffered SSE.
- Existing ScarletX UI behavior and styling remain unchanged apart from moving runtime-injected auth UI into static frontend source.
- Current release metadata remains `0.3.7`; do not publish or repoint a stable release tag in this change.

---

### Task 1: Establish the backend-only HTTP boundary

**Files:**
- Create: `tests/test_nginx_boundary.py`
- Modify: `scarletx/app.py`
- Modify: `scarletx/main.py`
- Modify: `scarletx/__main__.py`
- Delete: `scarletx/auth_ui.py`
- Modify: `tests/test_auth_ui.py`
- Modify: `tests/test_auth_middleware.py`

**Interfaces:**
- Produces backend ASGI app `scarletx.app:app` with auth routes and security middleware.
- Backend exposes API/framework routes only; `/` is not a FastAPI UI route.
- `python -m scarletx` starts backend on `SCARLETX_PORT`, default `8000`.

- [ ] **Step 1: Add failing boundary tests**

Add assertions that production FastAPI returns 404 for `/`, `scarletx/app.py` does not import/install `auth_ui`, `scarletx/main.py` contains no `WEB =` frontend path and no `@app.get("/")`, and `scarletx/__main__.py` defaults to port `8000`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_nginx_boundary.py tests/test_auth_ui.py tests/test_auth_middleware.py -q`

Expected: failures because FastAPI still owns `/`, auth UI is runtime-injected, and backend defaults to 8690.

- [ ] **Step 3: Remove backend UI serving**

Change `scarletx/app.py` to compose only auth router + auth/security middleware. Remove `install_auth_ui` and `Path` imports. Remove `WEB` and the `/` route from `scarletx/main.py`. Change `scarletx/__main__.py` default port to 8000.

- [ ] **Step 4: Remove runtime UI injector**

Delete `scarletx/auth_ui.py`. Replace its unit tests with static-frontend tests in Task 2.

- [ ] **Step 5: Verify GREEN for backend boundary**

Run the same focused test command and require zero failures.

- [ ] **Step 6: Commit**

Commit message: `Separate ScarletX backend from web UI`.

---

### Task 2: Make authentication and the existing UI fully static

**Files:**
- Create: `frontend/index.html`
- Create: `frontend/auth.css`
- Create: `frontend/auth.js`
- Delete: `scarletx/web/index.html`
- Rewrite: `tests/test_auth_ui.py`
- Extend: `tests/test_nginx_boundary.py`

**Interfaces:**
- `frontend/index.html` is the complete existing ScarletX SPA source.
- `frontend/auth.css` contains the existing auth-gate/account styles currently held in Python.
- `frontend/auth.js` owns setup/login/logout/account behavior and calls relative `/api/...` URLs only.
- Existing `boot()` function is invoked only after `/api/auth/status` reports an authenticated session.

- [ ] **Step 1: Write failing static frontend tests**

Assert `frontend/index.html`, `frontend/auth.css`, and `frontend/auth.js` exist; index references both assets; auth JS contains `/api/auth/status`, `/api/setup/admin`, `/api/auth/login`, `/api/auth/logout`, and `/api/auth/admin`; index contains the auth gate/account markup; legacy direct `boot();` is replaced by auth-gated startup; no `scarletx/auth_ui.py` exists.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_auth_ui.py tests/test_nginx_boundary.py -q`.

Expected: missing frontend files and old runtime-injection assumptions.

- [ ] **Step 3: Extract auth CSS/JS from the former Python injector**

Move the exact existing auth styling and behavior into `frontend/auth.css` and `frontend/auth.js`. Keep same-origin cookies and relative API paths. Do not persist credentials in browser storage.

- [ ] **Step 4: Move the SPA source**

Copy the current `scarletx/web/index.html` to `frontend/index.html`, add `<link rel="stylesheet" href="/auth.css">`, insert the existing auth gate/account/dialog markup at the top of `<body>`, add `<script src="/auth.js"></script>`, and replace the final direct `boot();` call with `authGateBoot(boot);`.

- [ ] **Step 5: Verify GREEN**

Run the focused frontend/boundary tests and require zero failures.

- [ ] **Step 6: Commit**

Commit message: `Make ScarletX frontend a static application`.

---

### Task 3: Put Nginx in front of the backend for Docker deployments

**Files:**
- Create: `nginx/scarletx.conf`
- Create: `Dockerfile.web`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Extend: `tests/test_nginx_boundary.py`

**Interfaces:**
- Nginx upstream name: `scarletx-backend:8000`.
- Web container listens on 8690.
- Backend container exposes 8000 only.

- [ ] **Step 1: Add failing deployment-contract tests**

Assert Nginx config listens on 8690, uses `/usr/share/nginx/html`, proxies `/api/` and docs/OpenAPI to `http://scarletx-backend:8000`, forwards `Host`, `X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto`, and disables buffering for `/api/activity/stream`. Assert Dockerfile backend uses port 8000 and Dockerfile.web copies `frontend/` plus Nginx config. Assert Compose publishes only `scarletx-web`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_nginx_boundary.py -q`.

Expected: missing Nginx/web image/two-service Compose contract.

- [ ] **Step 3: Add Nginx config**

Configure static SPA fallback and reverse proxy. For SSE set `proxy_buffering off`, `proxy_cache off`, and long read timeout. Preserve forwarded headers for every proxied location.

- [ ] **Step 4: Add web image**

`Dockerfile.web` uses `nginx:alpine`, removes default config, copies `nginx/scarletx.conf` and `frontend/`, exposes 8690, and health-checks `/api/health` through Nginx.

- [ ] **Step 5: Convert backend image to internal port 8000**

Change `SCARLETX_PORT`, `EXPOSE`, and healthcheck in `Dockerfile` from 8690 to 8000. Keep application/data dependencies unchanged.

- [ ] **Step 6: Convert Compose to two services**

Rename Python service `scarletx-backend`, remove its `ports`, retain its environment/volumes, and add `scarletx-web` with host `8690:8690`, backend health dependency, and no app-data mounts.

- [ ] **Step 7: Verify GREEN**

Run focused deployment-contract tests and require zero failures.

- [ ] **Step 8: Commit**

Commit message: `Route ScarletX through Nginx`.

---

### Task 4: Route the TrueNAS Community App through Nginx

**Files:**
- Modify: `packaging/truenas/scarletx/ix_values.yaml`
- Modify: `packaging/truenas/scarletx/templates/docker-compose.yaml`
- Modify: `packaging/truenas/scarletx/app.yaml` only for catalog revision if required by changed packaging
- Modify: `packaging/truenas/scarletx/templates/test_values/basic-values.yaml` only if container-specific values are required
- Extend: `tests/test_nginx_boundary.py`

**Interfaces:**
- TrueNAS container names: `scarletx-backend` and `scarletx-web`.
- Published `values.network.web_port` is attached only to `scarletx-web`.
- Persistent storage, env vars, UID/GID, and permissions attach only to backend.
- Portal targets web service.

- [ ] **Step 1: Add failing TrueNAS separation tests**

Assert `ix_values.yaml` declares backend and web images; template creates two containers; web receives `add_port`; backend receives storage/environment/user; web depends on backend health; portal remains based on the published web port.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_nginx_boundary.py tests/test_release_contract.py -q`.

Expected: TrueNAS template still creates one Python container.

- [ ] **Step 3: Add web image metadata**

Declare a second image repository/tag for the Nginx web image while keeping release version synchronization explicit.

- [ ] **Step 4: Render two TrueNAS containers**

Backend keeps current non-root identity, settings, storage, permissions, and backend healthcheck on internal port 8000. Web owns `values.network.web_port`, depends on backend health, and has a healthcheck through Nginx `/api/health`.

- [ ] **Step 5: Keep release contract synchronized**

If catalog source changes require a catalog revision bump, update only the catalog `version`; keep `app_version: 0.3.7` until a new ScarletX release is deliberately created. Update release-contract tests accordingly.

- [ ] **Step 6: Verify focused tests**

Run: `python -m pytest tests/test_nginx_boundary.py tests/test_release_contract.py -q`.

- [ ] **Step 7: Run source compilation**

Run: `python -m compileall -q scarletx tests`.

- [ ] **Step 8: Run complete Python tests**

Run: `python -m pytest -q`.

- [ ] **Step 9: Validate TrueNAS render**

Overlay `packaging/truenas/scarletx` into the current upstream `truenas/apps` checkout and run its ScarletX render validation for `basic-values.yaml`.

- [ ] **Step 10: Commit**

Commit message: `Route TrueNAS ScarletX app through Nginx`.

---

### Task 5: Branch verification and review

**Files:**
- Review all changes from `main...nginx-frontend-backend-split`.

**Interfaces:**
- Produces a reviewable branch; no merge is part of this task unless explicitly requested after verification.

- [ ] **Step 1: Verify no backend UI coupling remains**

Confirm no runtime import/reference to `auth_ui`, `scarletx/web/index.html`, or FastAPI `/` frontend route remains.

- [ ] **Step 2: Verify only Nginx is public in deployment definitions**

Confirm Compose and TrueNAS publish only the web port.

- [ ] **Step 3: Verify frontend API calls remain relative**

Confirm no frontend reference to `scarletx-backend`, `localhost:8000`, or direct Uvicorn URL exists.

- [ ] **Step 4: Verify current-head CI**

Open a PR to `main`, then require the exact head SHA to pass the existing Python 3.11/3.12/3.13 tests and relevant TrueNAS validation before any merge recommendation.
