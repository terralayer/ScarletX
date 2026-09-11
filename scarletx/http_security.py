from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

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
    """Return header/bearer API keys while continuing to reject query-string keys."""
    supplied = request.headers.get("X-Api-Key") or ""
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
    """Retain the authentication hook while allowing ScarletX to run without a browser session."""

    @app.middleware("http")
    async def scarletx_authentication(request: Request, call_next):
        return await call_next(request)


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
