# ScarletX Nginx Frontend/Backend Separation Design

## Goal

Make Nginx the only public HTTP entrypoint for ScarletX. Nginx serves the static frontend and proxies every backend HTTP request to an internal FastAPI/Uvicorn service. The browser never connects directly to Uvicorn.

## Architecture

ScarletX runs as two cooperating containers in normal Docker/TrueNAS deployment:

- `scarletx-web`: Nginx. This is the only container with a published host port.
- `scarletx-backend`: Python/Uvicorn. This listens only on the private container network.

Request flow:

```text
Browser
  |
  v
Nginx :8690 (or TrueNAS published port)
  |-- /, /assets/*, frontend files -> static frontend
  |-- /api/*                      -> http://scarletx-backend:8000
  |-- /docs                       -> http://scarletx-backend:8000
  |-- /redoc                      -> http://scarletx-backend:8000
  `-- /openapi.json               -> http://scarletx-backend:8000
```

Nginx preserves the original request host, client address forwarding headers, upgrade headers, and streaming behavior. `/api/activity/stream` must not be buffered so server-sent events remain live.

## Frontend Boundary

The frontend remains the existing ScarletX HTML/CSS/JavaScript application. This change does not redesign it.

The authentication shell currently injected at runtime by `scarletx/auth_ui.py` becomes part of the static frontend source. Frontend authentication continues to use same-origin requests to `/api/auth/status`, `/api/setup/admin`, `/api/auth/login`, `/api/auth/logout`, and `/api/auth/admin`.

The frontend must not import Python modules, depend on Python template injection, or know the backend container hostname. It talks only to relative HTTP paths such as `/api/...`.

## Backend Boundary

FastAPI owns API, auth, database, media, downloader, automation, and framework documentation endpoints only. It no longer serves the root ScarletX UI.

`scarletx/app.py` remains the backend composition module. It includes authentication routes and security middleware but no longer installs `auth_ui` middleware. `scarletx/main.py` no longer defines the `/` route or references `scarletx/web/index.html`.

The backend process listens on `0.0.0.0:8000` inside its container by default. No host port is published for it.

## Nginx Routing

Create `nginx/scarletx.conf` with these rules:

- Static root is `/usr/share/nginx/html`.
- `/api/` proxies to `http://scarletx-backend:8000` without stripping `/api`.
- `/docs`, `/redoc`, and `/openapi.json` proxy to the backend so existing authentication middleware still protects them.
- `/api/activity/stream` disables proxy buffering and response caching.
- `/` uses `try_files $uri $uri/ /index.html` to keep the SPA usable.
- Backend responses continue to supply ScarletX security headers; Nginx does not weaken or overwrite them.

## Container Images

Use separate Dockerfiles:

- `Dockerfile` remains the backend image and exposes internal port `8000`.
- `Dockerfile.web` builds from `nginx:alpine`, copies the static frontend into `/usr/share/nginx/html`, and installs `nginx/scarletx.conf`.

The backend health check targets `http://127.0.0.1:8000/api/health`. The web container health check targets `http://127.0.0.1:8690/api/health`, proving the complete Nginx-to-backend path works.

## Docker Compose

`docker-compose.yml` defines both services on the same private Compose network.

`scarletx-backend`:

- built from `Dockerfile`;
- receives all existing environment variables and persistent storage mounts;
- does not publish a host port;
- listens on port `8000`.

`scarletx-web`:

- built from `Dockerfile.web`;
- depends on a healthy backend;
- publishes host port `8690` to container port `8690`;
- has no application data mounts.

## TrueNAS Packaging

The TrueNAS Community App must follow the same boundary rather than bypass Nginx.

The application definition will contain a backend container and an Nginx web container. Only the Nginx web container receives the TrueNAS published WebUI port. Persistent storage and runtime settings stay on the backend container. The portal points at Nginx.

The backend and web image versions stay synchronized with the ScarletX release version. The current release remains `0.3.7`; this architectural work does not invent a new public stable tag until the normal release process is followed.

## Authentication and Client IPs

Because login rate limiting uses the client address, Nginx must forward `X-Forwarded-For`, `X-Real-IP`, `Host`, and `X-Forwarded-Proto`.

The backend must resolve the effective client address from trusted proxy forwarding data only for the Nginx deployment path. For this stage, Nginx is the only supported public HTTP entrypoint in container deployment; direct backend exposure is not part of the deployment contract.

Session cookies remain same-origin because both frontend and API are presented by the same Nginx origin.

## Streaming and Large Media

Nginx proxies media and generated-art endpoints under `/api/*` rather than serving application storage directly. This preserves FastAPI authorization and existing `FileResponse` behavior.

Proxy request buffering is disabled for streaming-sensitive paths where needed. Response buffering is disabled for `/api/activity/stream`.

## Compatibility

Preserve:

- existing `/api/*` URLs;
- `/api/health` response contract;
- API-key automation through Nginx;
- browser-session authentication;
- current TrueNAS persistent storage paths;
- current ScarletX UI behavior and styling;
- Python 3.11/3.12/3.13 backend test compatibility.

Direct `python -m scarletx` remains useful for backend development, but it starts the backend service only. The supported full application deployment is Nginx plus backend.

## Tests

Add focused regression coverage that asserts:

- FastAPI no longer owns `/`;
- `scarletx.app` no longer installs `auth_ui`;
- the static frontend contains the auth gate and delays application boot until authentication succeeds;
- Nginx config proxies `/api/*`, docs/OpenAPI, and disables buffering for SSE;
- Compose publishes only the web service port and leaves backend internal;
- backend Dockerfile listens/health-checks on port `8000`;
- web Dockerfile serves the static frontend through Nginx;
- TrueNAS render definitions route the portal/public port through Nginx rather than the backend.

## Non-Goals

This change does not:

- rewrite the frontend in React/Vue/Svelte;
- change existing API contracts;
- split backend domain modules beyond removing UI-serving responsibility;
- add TLS termination or certificate management;
- expose media files directly from Nginx;
- replace existing authentication/session logic.
