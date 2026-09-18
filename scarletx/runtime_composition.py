from __future__ import annotations

from .activity_history import activity_history_page
from .auth_routes import router as auth_router
from .operations_routes import router as operations_router
from .bulk_operations import bulk_wanted
from .compact_studio_art import install_compact_studio_art_route
from .db import SessionLocal, engine
from .downloader_state_hotfix import install_downloader_state_hotfixes
from .http_security import (
    install_authentication,
    install_security_headers,
    remove_legacy_api_key_middleware,
)
from .library_health import library_health
from .media_dedup import install_runtime_dedup
from .observability import install_observability
from .observability_routes import system_metrics
from .routes.runtime_overrides import (
    dashboard_performers_runtime,
    dashboard_scenes_runtime,
    dashboard_studios_runtime,
    update_general_settings_runtime,
)
from .settings_store import load_database_settings


def _fixed_runtime_settings(db, *args, **kwargs):
    return load_database_settings(db, *args, **kwargs)


def _remove_legacy_web_route(app) -> None:
    app.router.routes = [
        route for route in app.router.routes if getattr(route, "path", None) != "/"
    ]


def _patch_route_call(app, path: str, method: str, replacement) -> None:
    method = method.upper()
    for route in app.router.routes:
        if (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        ):
            route.endpoint = replacement
            route.dependant.call = replacement
            return
    raise RuntimeError(f"ScarletX route not found: {method} {path}")


def _add_route(app, path: str, endpoint, *, method: str, name: str) -> None:
    if any(getattr(route, "path", None) == path for route in app.router.routes):
        return
    app.add_api_route(path, endpoint, methods=[method], name=name)


def _add_runtime_routes(app) -> None:
    definitions = (
        (
            "/api/dashboard/scenes",
            dashboard_scenes_runtime,
            "GET",
            "dashboard_downloaded_scenes",
        ),
        (
            "/api/dashboard/studios",
            dashboard_studios_runtime,
            "GET",
            "dashboard_recent_studios",
        ),
        (
            "/api/dashboard/performers",
            dashboard_performers_runtime,
            "GET",
            "dashboard_recent_performers",
        ),
        ("/api/wanted/bulk", bulk_wanted, "POST", "bulk_wanted"),
        ("/api/history/page", activity_history_page, "GET", "activity_history_page"),
        ("/api/media-library/health", library_health, "GET", "library_health"),
        ("/api/system/metrics", system_metrics, "GET", "system_metrics"),
    )
    for path, endpoint, method, name in definitions:
        _add_route(app, path, endpoint, method=method, name=name)


def install_runtime_composition(app, legacy_application) -> None:
    """Install focused runtime overrides while preserving the legacy route contract."""
    _remove_legacy_web_route(app)
    legacy_application.load_database_settings = _fixed_runtime_settings
    _patch_route_call(
        app,
        "/api/settings/general",
        "PATCH",
        update_general_settings_runtime,
    )
    _add_runtime_routes(app)
    install_runtime_dedup(legacy_application)
    install_downloader_state_hotfixes(app)
    install_compact_studio_art_route(app)
    remove_legacy_api_key_middleware(app)
    app.include_router(auth_router)
    app.include_router(operations_router)
    install_authentication(
        app,
        session_factory=SessionLocal,
        settings_loader=_fixed_runtime_settings,
    )
    install_security_headers(app)
    install_observability(app, engine)
