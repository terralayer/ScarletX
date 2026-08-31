# ScarletX 0.3.8

ScarletX 0.3.8 separates the web frontend from the FastAPI backend and makes Nginx the only supported public HTTP entrypoint for container deployments.

## Highlights

- Adds a dedicated `scarletx-web` Nginx container for the static ScarletX frontend.
- Moves the frontend source out of the Python package into `frontend/`.
- Keeps the FastAPI backend private on internal port `8000` with no published host port.
- Routes `/api/*`, `/docs`, `/redoc`, and `/openapi.json` through Nginx.
- Preserves live activity streaming by disabling Nginx buffering for `/api/activity/stream`.
- Removes runtime Python auth-UI injection; setup, login, logout, and account management are now static same-origin frontend behavior.
- Adds explicit trusted-proxy handling so login rate limiting sees the real client address and secure cookies honor forwarded HTTPS only in Nginx deployments.
- Splits Docker Compose and TrueNAS deployment definitions into `scarletx-backend` and `scarletx-web` services.
- Keeps persistent configuration, downloads, media, and backups attached only to the backend container.
- Keeps the TrueNAS WebUI port configurable while publishing it only from Nginx.
- Adds CI coverage that builds both real Docker images in addition to Python 3.11/3.12/3.13 tests and TrueNAS rendering.

## Upgrade notes

Existing ScarletX configuration and storage paths are preserved. Container deployments now require both matching 0.3.8 images:

- `ghcr.io/terralayer/scarletx:0.3.8`
- `ghcr.io/terralayer/scarletx-web:0.3.8`

The browser should connect only to the Nginx/WebUI port. Port `8000` is an internal backend port and should not be published directly.
