from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    create_session,
    hash_password,
    login_limiter,
    normalize_username,
    revoke_all_sessions,
    revoke_session,
    session_user,
    verify_password_and_update,
)
from .db import get_session
from .models import AppSetting, AuthUser
from .settings_store import set_setting
from .setup_security import consume_setup_token
from .schemas import AdminCredentialsWrite, AdminSetupWrite, LoginWrite, SetupAgreementAcceptWrite

router = APIRouter()

SETUP_AGREEMENT_VERSION = "2026-09-21"
SETUP_AGREEMENT_ACCEPTED_AT_KEY = "setup_agreement_accepted_at"
SETUP_AGREEMENT_VERSION_KEY = "setup_agreement_version"
SETUP_AGREEMENT_LINKS = {
    "license": "https://github.com/terralayer/ScarletX/blob/main/LICENSE",
    "project": "https://github.com/terralayer/ScarletX",
}


def _agreement_value(db: Session, key: str) -> str | None:
    item = db.get(AppSetting, key)
    value = (item.value or "").strip() if item is not None else ""
    return value or None


def _agreement_status(db: Session) -> dict:
    accepted_at = _agreement_value(db, SETUP_AGREEMENT_ACCEPTED_AT_KEY)
    accepted_version = _agreement_value(db, SETUP_AGREEMENT_VERSION_KEY)
    return {
        "required": not _admin_exists(db) and accepted_at is None,
        "accepted": accepted_at is not None,
        "accepted_at": accepted_at,
        "version": accepted_version or SETUP_AGREEMENT_VERSION,
        "current_version": SETUP_AGREEMENT_VERSION,
        "links": SETUP_AGREEMENT_LINKS,
    }


def _trust_proxy_headers() -> bool:
    return os.getenv("SCARLETX_TRUST_PROXY_HEADERS", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _client_address(request: Request) -> str:
    if _trust_proxy_headers():
        # Nginx overwrites X-Real-IP with the connection peer address, so it is
        # not affected by a client-supplied X-Forwarded-For value.
        real_ip = (request.headers.get("X-Real-IP") or "").strip()
        if real_ip:
            return real_ip
        forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _request_is_secure(request: Request) -> bool:
    if _trust_proxy_headers():
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().casefold()
        if forwarded_proto:
            return forwarded_proto == "https"
    return request.url.scheme == "https"


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=_request_is_secure(request),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=_request_is_secure(request),
        httponly=True,
        samesite="lax",
    )


def _admin_exists(db: Session) -> bool:
    return db.scalar(select(AuthUser.id).limit(1)) is not None


def _current_user(request: Request, db: Session) -> AuthUser | None:
    token = request.cookies.get(SESSION_COOKIE_NAME) or ""
    return session_user(db, token)


@router.get("/api/setup/status")
def setup_status(db: Session = Depends(get_session)):
    return {"setup_required": not _admin_exists(db)}


@router.get("/api/setup/agreement")
def setup_agreement_status(db: Session = Depends(get_session)):
    return _agreement_status(db)


@router.post("/api/setup/agreement")
def accept_setup_agreement(
    payload: SetupAgreementAcceptWrite,
    db: Session = Depends(get_session),
):
    if _admin_exists(db):
        raise HTTPException(409, "Administrator already configured")
    if payload.version != SETUP_AGREEMENT_VERSION:
        raise HTTPException(409, "Agreement version is no longer current; reload setup and review it again")

    current = _agreement_value(db, SETUP_AGREEMENT_ACCEPTED_AT_KEY)
    if current is None:
        accepted_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        set_setting(db, SETUP_AGREEMENT_ACCEPTED_AT_KEY, accepted_at, commit=False)
        set_setting(db, SETUP_AGREEMENT_VERSION_KEY, SETUP_AGREEMENT_VERSION, commit=False)
        db.commit()
    return _agreement_status(db)


@router.get("/api/setup/api-key")
def setup_api_key(response: Response, db: Session = Depends(get_session)):
    if _admin_exists(db):
        raise HTTPException(409, "Administrator already configured")
    response.headers["Cache-Control"] = "no-store"
    return {"api_key": secrets.token_urlsafe(32)}


@router.post("/api/setup/admin")
def setup_admin(
    payload: AdminSetupWrite,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
):
    if _admin_exists(db):
        raise HTTPException(409, "Administrator already configured")
    if _agreement_value(db, SETUP_AGREEMENT_ACCEPTED_AT_KEY) is None:
        raise HTTPException(428, "Accept the ScarletX usage agreement before creating the administrator")

    user = AuthUser(
        id=1,
        username=payload.username,
        username_normalized=normalize_username(payload.username),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        set_setting(db, "ui_auth_enabled", "true", commit=False)
        set_setting(db, "api_key_enabled", "true", commit=False)
        set_setting(db, "api_key", payload.api_key, commit=False)
        db.commit()
        db.refresh(user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Administrator already configured") from exc

    token = create_session(db, user.id)
    consume_setup_token()
    _set_session_cookie(response, request, token)
    return {"username": user.username}


@router.get("/api/auth/status")
def auth_status(request: Request, db: Session = Depends(get_session)):
    enabled = True
    setup_required = not _admin_exists(db)
    agreement = _agreement_status(db)
    user = None if setup_required else _current_user(request, db)
    return {
        "enabled": enabled,
        "setup_required": setup_required,
        "agreement_required": bool(agreement["required"]),
        "authenticated": user is not None,
        "username": user.username if user else None,
    }


@router.post("/api/auth/login")
def login(
    payload: LoginWrite,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
):
    address = _client_address(request)
    if login_limiter.is_blocked(address):
        raise HTTPException(429, "Too many login attempts")

    normalized = normalize_username(payload.username)
    user = db.scalar(
        select(AuthUser).where(AuthUser.username_normalized == normalized).limit(1)
    )
    if user is None:
        login_limiter.record_failure(address)
        raise HTTPException(401, "Invalid username or password")

    valid, replacement_hash = verify_password_and_update(payload.password, user.password_hash)
    if not valid:
        login_limiter.record_failure(address)
        raise HTTPException(401, "Invalid username or password")

    if replacement_hash:
        user.password_hash = replacement_hash
        db.commit()
    login_limiter.clear(address)
    token = create_session(db, user.id)
    _set_session_cookie(response, request, token)
    return {"username": user.username}


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_session)):
    token = request.cookies.get(SESSION_COOKIE_NAME) or ""
    revoke_session(db, token)
    _clear_session_cookie(response, request)
    response.status_code = 204
    return None


@router.patch("/api/auth/admin")
def update_admin_credentials(
    payload: AdminCredentialsWrite,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
):
    token = request.cookies.get(SESSION_COOKIE_NAME) or ""
    user = session_user(db, token)
    if user is None:
        raise HTTPException(401, "Authentication required")

    user.username = payload.username
    user.username_normalized = normalize_username(payload.username)
    user.password_hash = hash_password(payload.password)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Username is already in use") from exc

    revoke_all_sessions(db, user.id)
    replacement = create_session(db, user.id)
    _set_session_cookie(response, request, replacement)
    return {"username": user.username}
