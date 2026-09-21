from __future__ import annotations

from collections.abc import Callable
import hmac
from urllib.parse import urlsplit
from sqlalchemy import select
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from .models import AuthUser
from .auth import SESSION_COOKIE_NAME, session_user

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
    """Require completed setup and a browser session or enabled integration key."""

    def authenticate(token: str, supplied: str) -> int | None:
        # Create, use and close the synchronous Session in the same worker thread.
        # Authorization itself is never cached: logout takes effect on the next request.
        with session_factory() as db:
            if session_user(db, token) is not None:
                return None
            if db.scalar(select(AuthUser.id).limit(1)) is None:
                return 403
            if supplied:
                # Read fresh settings so key rotation cannot use an older cached key.
                settings = settings_loader(db, force=True)
                key = settings.api_key.get_secret_value()
                if settings.api_key_enabled and key and hmac.compare_digest(key.encode(), supplied.encode()):
                    return None
            return 401

    @app.middleware("http")
    async def scarletx_authentication(request: Request, call_next):
        path = request.url.path
        protected = path.startswith("/api/") or path in {"/docs", "/redoc", "/openapi.json"}
        public = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout", "/api/setup/status", "/api/setup/agreement", "/api/setup/admin", "/api/setup/api-key"}
        if protected and request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and (origin == "null" or urlsplit(origin).netloc != request.url.netloc):
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        if protected and path not in public:
            status = await run_in_threadpool(
                authenticate, request.cookies.get(SESSION_COOKIE_NAME) or "", _supplied_api_key(request)
            )
            if status is not None:
                detail = "Initial setup required" if status == 403 else "Authentication required"
                return JSONResponse({"detail": detail}, status_code=status)
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
