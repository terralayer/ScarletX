from __future__ import annotations

from .auth_routes import router as auth_router
from .db import SessionLocal
from .http_security import install_authentication, install_security_headers, remove_legacy_api_key_middleware
from .main import app
from .settings_store import load_database_settings


def _remove_legacy_web_route() -> None:
    """Keep the composed ASGI app backend-only while main.py is decomposed incrementally."""
    app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) != "/"]


# The legacy module still owns the domain API routes. The public web surface is
# now Nginx, so remove its old root HTML route and API-key-only middleware before
# composing the current authentication/security layers.
_remove_legacy_web_route()
remove_legacy_api_key_middleware(app)
app.include_router(auth_router)
install_authentication(
    app,
    session_factory=SessionLocal,
    settings_loader=load_database_settings,
)
install_security_headers(app)
