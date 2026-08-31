from __future__ import annotations

from .auth_routes import router as auth_router
from .db import SessionLocal
from .http_security import install_authentication, install_security_headers, remove_legacy_api_key_middleware
from .main import app
from .settings_store import load_database_settings

# Replace the legacy API-key-only gate with combined browser-session/API-key auth.
remove_legacy_api_key_middleware(app)
app.include_router(auth_router)
install_authentication(
    app,
    session_factory=SessionLocal,
    settings_loader=load_database_settings,
)
install_security_headers(app)
