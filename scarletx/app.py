from __future__ import annotations

from .auth_routes import router as auth_router
from .db import SessionLocal
from .http_security import install_authentication, install_security_headers, remove_legacy_api_key_middleware
from .main import app
from .media_dedup import install_runtime_dedup
from .routes import application as legacy_application
from .routes.runtime_overrides import router as runtime_overrides_router
from .settings_store import load_database_settings


def _remove_legacy_web_route() -> None:
    """Keep the composed ASGI app backend-only while main.py is decomposed incrementally."""
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/"]


def _remove_legacy_api_route(path: str, method: str) -> None:
    method = method.upper()
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


# The legacy module still owns most domain API routes. Nginx owns the public web
# surface, while small corrected contracts are composed here without rewriting the
# legacy route monolith.
_remove_legacy_web_route()
_remove_legacy_api_route("/api/library/scenes/page", "GET")
_remove_legacy_api_route("/api/settings/general", "PATCH")
install_runtime_dedup(legacy_application)
remove_legacy_api_key_middleware(app)
app.include_router(runtime_overrides_router)
app.include_router(auth_router)
install_authentication(
    app,
    session_factory=SessionLocal,
    settings_loader=load_database_settings,
)
install_security_headers(app)
