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
  |-- /, frontend files            -> static frontend
  |-- /api/*                       -> http://scarletx-backend:8000
  |-- /docs                        -> http://scarletx-backend:8000
  |-- /redoc                       -> http://scarletx-backend:8000
  `-- /openapi.json                -> http://scarletx-backend:8000
```

Nginx preserves the original request host and forwarding headers. `/api/activity/stream` is not buffered so server-sent events remain live.

## Frontend Boundary

The frontend remains the existing ScarletX HTML/CSS/JavaScript application. This change does not redesign it.

Frontend source lives under `frontend/`, outside the Python package. The former Python-injected authentication shell is implemented by static `frontend/auth.css` and `frontend/auth.js`. The web image bakes those static assets into the existing UI shell at image-build time; no Python request-time HTML rewriting remains.

Frontend authentication uses same-origin requests to `/api/auth/status`, `/api/setup/admin`, `/api/auth/login`, `/api/auth/logout`, and `/api/auth/admin`. The frontend does not know the backend container hostname or port.

## Backend Boundary

The supported backend entrypoint is `scarletx.app:app`. FastAPI owns API, auth, database, media, downloader, automation, and framework documentation endpoints only. The composed production app does not serve `/`.

`scarletx/main.py` remains the legacy domain/API monolith during this stage. It still registers the historic root route internally, but the frontend source it formerly referenced has been removed from the Python package and `scarletx/app.py` removes that root route while composing the supported backend app. This preserves a focused architecture change without requiring an unrelated full decomposition of the backend monolith.

Direct use of `scarletx.main:app` is not a supported deployment entrypoint. `python -m scarletx` runs `scarletx.app:app` and defaults to internal port `8000`.

## Nginx Routing

`nginx/scarletx.conf` provides these rules:

- Static root is `/usr/share/nginx/html`.
- The listen port is supplied by `SCARLETX_WEB_PORT`; normal Compose uses `8690`, while TrueNAS supplies its configured WebUI port.
- `/api/` proxies to `http://scarletx-backend:8000` without stripping `/api`.
- `/docs`, `/redoc`, and `/openapi.json` proxy to the backend so existing authentication middleware protects them.
- `/api/activity/stream` disables proxy buffering and response caching.
- `/` uses `try_files $uri $uri/ /index.html`.
- Nginx forwards `Host`, `X-Real-IP`, `X-Forwarded-For`, and `X-Forwarded-Proto`.

## Container Images

Use separate Dockerfiles:

- `Dockerfile` is the backend image and exposes internal port `8000`.
- `Dockerfile.web` is the Nginx image and contains only static frontend/gateway concerns.

The backend health check targets `http://127.0.0.1:8000/api/health`. The web container health check targets `/api/health` through Nginx, proving the Nginx-to-backend path works.

The web image is safe to run as a non-root user and supports TrueNAS overriding the UID/GID.

## Docker Compose

`docker-compose.yml` defines both services on the same private Compose network.

`scarletx-backend`:

- built from `Dockerfile`;
- receives application environment variables and persistent storage mounts;
- does not publish a host port;
- listens on port `8000`;
- enables trusted proxy headers because Nginx is its deployment ingress.

`scarletx-web`:

- built from `Dockerfile.web`;
- depends on a healthy backend;
- publishes host port `8690` to container port `8690`;
- has no application data mounts.

`docker-compose.truenas.yml` follows the same two-container boundary.

## TrueNAS Packaging

The TrueNAS Community App contains a backend container and an Nginx web container. Only the Nginx web container receives the TrueNAS published WebUI port. Persistent storage and application runtime settings stay on the backend container. The portal targets Nginx.

The web container receives the configured TrueNAS WebUI port through `SCARLETX_WEB_PORT`, so the catalog default/custom port is also the Nginx listen port. Both containers run non-root.

The backend and web image versions stay synchronized with the ScarletX release version. The architectural branch keeps application metadata at `0.3.7`; it does not repoint the already released stable backend tag. A subsequent release must publish matching backend and web images before this packaging becomes a deployable stable release.

## Authentication and Client IPs

Nginx overwrites and forwards `X-Real-IP`, plus `X-Forwarded-For`, `Host`, and `X-Forwarded-Proto`.

The backend trusts forwarding headers only when `SCARLETX_TRUST_PROXY_HEADERS` is explicitly enabled by the Nginx deployment definitions. This keeps direct development use from trusting arbitrary client-supplied proxy headers. Login rate limiting uses Nginx's `X-Real-IP`, and session cookie Secure handling honors the trusted forwarded scheme.

Session cookies remain same-origin because frontend and API are presented by the same Nginx origin.

## Streaming and Large Media

Nginx proxies media and generated-art endpoints under `/api/*` rather than serving application storage directly. This preserves FastAPI authorization and existing `FileResponse` behavior.

Proxy request buffering is disabled for API traffic where large/streaming requests may occur. Response buffering is disabled for `/api/activity/stream`.

## Compatibility

Preserve:

- existing `/api/*` URLs;
- `/api/health` response contract;
- API-key automation through Nginx;
- browser-session authentication;
- current TrueNAS persistent storage paths;
- current ScarletX UI behavior and styling;
- Python 3.11/3.12/3.13 backend test compatibility.

## Tests and Verification

Regression coverage asserts:

- composed FastAPI no longer owns `/`;
- runtime `auth_ui` injection is absent;
- frontend source is outside the Python package;
- static auth uses only same-origin API paths and delays application boot until authentication succeeds;
- Nginx proxies `/api/*`, docs/OpenAPI, and disables buffering for SSE;
- Compose publishes only the web service port and leaves backend internal;
- backend Dockerfile listens/health-checks on port `8000` and does not copy frontend source;
- web Dockerfile builds the static frontend through Nginx;
- trusted proxy identity/scheme handling is opt-in and tested;
- TrueNAS render definitions route the portal/public port through Nginx rather than backend;
- CI builds both backend and web container images in addition to the Python matrix and TrueNAS renderer.

## Non-Goals

This change does not:

- rewrite the frontend in React/Vue/Svelte;
- change existing API contracts;
- fully split the legacy backend monolith into routers/services;
- add TLS termination or certificate management;
- expose media files directly from Nginx;
- replace existing authentication/session logic.
