from __future__ import annotations

import secrets
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import SESSION_COOKIE_NAME, session_user
from .models import AuthUser

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/login",
    "/api/setup/status",
    "/api/setup/admin",
}
PROTECTED_FRAMEWORK_PATHS = {"/docs", "/redoc", "/openapi.json"}
AUTH_CACHE_BYPASS_PREFIXES = ("/api/auth/", "/api/setup/")


def remove_legacy_api_key_middleware(app: FastAPI) -> bool:
    """Remove the pre-authentication API-key-only middleware from the legacy app."""
    retained = []
    removed = False
    for item in app.user_middleware:
        kwargs = getattr(item, "kwargs", {}) or {}
        dispatch = kwargs.get("dispatch")
        if (
            getattr(item, "cls", None) is BaseHTTPMiddleware
            and getattr(dispatch, "__name__", "") == "optional_api_key_auth"
        ):
            removed = True
            continue
        retained.append(item)
    if removed:
        app.user_middleware = retained
        app.middleware_stack = None
    return removed


def _supplied_api_key(request: Request) -> str:
    supplied = request.headers.get("X-Api-Key") or request.query_params.get("apikey") or ""
    authorization = request.headers.get("Authorization") or ""
    if not supplied and authorization.casefold().startswith("bearer "):
        supplied = authorization[7:].strip()
    return supplied


def install_authentication(
    app: FastAPI,
    *,
    session_factory,
    settings_loader: Callable,
) -> None:
    """Require a browser session or enabled ScarletX API key for private HTTP routes."""

    @app.middleware("http")
    async def scarletx_authentication(request: Request, call_next):
        path = request.url.path
        requires_auth = path.startswith("/api/") or path in PROTECTED_FRAMEWORK_PATHS
        if not requires_auth or path in PUBLIC_API_PATHS:
            return await call_next(request)

        authenticated = False
        try:
            with session_factory() as db:
                admin_exists = db.scalar(select(AuthUser.id).limit(1)) is not None
                if not admin_exists:
                    return JSONResponse(
                        {"detail": "Administrator setup is required"},
                        status_code=401,
                    )

                token = request.cookies.get(SESSION_COOKIE_NAME) or ""
                if token and session_user(db, token) is not None:
                    authenticated = True
                else:
                    settings = settings_loader(db)
                    if settings.api_key_enabled:
                        expected = settings.api_key.get_secret_value()
                        supplied = _supplied_api_key(request)
                        authenticated = bool(
                            expected and secrets.compare_digest(supplied, expected)
                        )
        except Exception:
            return JSONResponse(
                {"detail": "ScarletX authentication is temporarily unavailable"},
                status_code=503,
            )

        if authenticated:
            return await call_next(request)
        return JSONResponse({"detail": "Authentication required"}, status_code=401)


def install_security_headers(app: FastAPI) -> None:
    """Apply browser hardening headers to every ScarletX HTTP response."""

    @app.middleware("http")
    async def scarletx_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith(AUTH_CACHE_BYPASS_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
        return response
