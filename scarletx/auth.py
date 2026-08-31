from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .models import AuthSession, AuthUser

PASSWORD_HASH = PasswordHash.recommended()
SESSION_COOKIE_NAME = "scarletx_session"
SESSION_DAYS = 30
SESSION_MAX_AGE_SECONDS = SESSION_DAYS * 24 * 60 * 60
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def hash_password(password: str) -> str:
    return PASSWORD_HASH.hash(password)


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        return PASSWORD_HASH.verify(password, encoded_hash)
    except Exception:
        return False


def verify_password_and_update(password: str, encoded_hash: str) -> tuple[bool, str | None]:
    """Verify a password and return a replacement hash when parameters need upgrading."""
    try:
        return PASSWORD_HASH.verify_and_update(password, encoded_hash)
    except Exception:
        return False, None


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def create_session(db: Session, user_id: int, now: datetime | None = None) -> str:
    now = _as_utc(now or datetime.now(UTC))
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            user_id=user_id,
            token_digest=_digest(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def session_user(db: Session, token: str, now: datetime | None = None) -> AuthUser | None:
    if not token:
        return None
    now = _as_utc(now or datetime.now(UTC))
    row = db.scalar(
        select(AuthSession).where(AuthSession.token_digest == _digest(token)).limit(1)
    )
    if row is None:
        return None
    if _as_utc(row.expires_at) <= now:
        db.delete(row)
        db.commit()
        return None

    user = db.get(AuthUser, row.user_id)
    if user is None:
        db.delete(row)
        db.commit()
        return None

    last_seen = _as_utc(row.last_seen_at)
    if now - last_seen >= SESSION_TOUCH_INTERVAL:
        row.last_seen_at = now
        db.commit()
    return user


def revoke_session(db: Session, token: str) -> None:
    if not token:
        return
    db.execute(delete(AuthSession).where(AuthSession.token_digest == _digest(token)))
    db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.commit()


class LoginLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300):
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(1, int(window_seconds))
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, address: str, now: float) -> deque[float]:
        events = self._events[address]
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        return events

    def is_blocked(self, address: str) -> bool:
        with self._lock:
            return len(self._prune(address, time.monotonic())) >= self.max_failures

    def record_failure(self, address: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(address, now).append(now)

    def clear(self, address: str) -> None:
        with self._lock:
            self._events.pop(address, None)


login_limiter = LoginLimiter()
