from __future__ import annotations

from .auth_routes import router as auth_router
from .db import SessionLocal
from .http_security import install_authentication, install_security_headers, remove_legacy_api_key_middleware
from .main import app
from .media_dedup import install_runtime_dedup
from .routes import application as legacy_application
from .routes.runtime_overrides import (
    dashboard_scenes_runtime,
    dashboard_studios_runtime,
    update_general_settings_runtime,
)
from .settings_store import load_database_settings


def _remove_legacy_web_route() -> None:
    """Keep the composed ASGI app backend-only while main.py is decomposed incrementally."""
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/"]


def _fixed_runtime_settings(db, *args, **kwargs):
    settings = load_database_settings(db, *args, **kwargs)
    return settings.model_copy(update={"app_name": "ScarletX"})


def _patch_route_call(path: str, method: str, replacement) -> None:
    method = method.upper()
    for route in app.router.routes:
        if (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        ):
            # Preserve the APIRoute object so the focused route-boundary modules
            # continue to own the exact registered object. Only change its call.
            route.endpoint = replacement
            route.dependant.call = replacement
            return
    raise RuntimeError(f"ScarletX route not found: {method} {path}")


def _add_dashboard_routes() -> None:
    definitions = (
        ("/api/dashboard/scenes", dashboard_scenes_runtime, "dashboard_downloaded_scenes"),
        ("/api/dashboard/studios", dashboard_studios_runtime, "dashboard_recent_studios"),
    )
    existing = {getattr(route, "path", None) for route in app.router.routes}
    for path, endpoint, name in definitions:
        if path in existing:
            continue
        app.add_api_route(path, endpoint, methods=["GET"], name=name)


# The legacy module still owns most domain API route objects. Patch behavior in
# place where possible so route ownership, middleware, and compatibility remain stable.
_remove_legacy_web_route()
legacy_application.load_database_settings = _fixed_runtime_settings
_patch_route_call("/api/settings/general", "PATCH", update_general_settings_runtime)
_add_dashboard_routes()
install_runtime_dedup(legacy_application)
remove_legacy_api_key_middleware(app)
app.include_router(auth_router)
install_authentication(
    app,
    session_factory=SessionLocal,
    settings_loader=_fixed_runtime_settings,
)
install_security_headers(app)
