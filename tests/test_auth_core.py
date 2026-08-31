from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from scarletx.auth import (
    LoginLimiter,
    create_session,
    hash_password,
    revoke_all_sessions,
    revoke_session,
    session_user,
    verify_password,
    verify_password_and_update,
)
from scarletx.db import Base
from scarletx.models import AuthSession, AuthUser


def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_user(db, password="correct-horse-battery"):
    user = AuthUser(
        username="admin",
        username_normalized="admin",
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_password_hash_is_argon2id_and_verifies():
    encoded = hash_password("correct-horse-battery")
    assert encoded.startswith("$argon2id$")
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("wrong-password", encoded)


def test_password_verification_supports_rehash_detection():
    encoded = hash_password("correct-horse-battery")
    valid, replacement = verify_password_and_update("correct-horse-battery", encoded)
    assert valid is True
    assert replacement is None or replacement.startswith("$argon2id$")


def test_session_database_contains_digest_not_raw_token():
    factory = session_factory()
    with factory() as db:
        user = add_user(db)
        token = create_session(db, user.id)
        stored = db.scalar(select(AuthSession))
        assert stored is not None
        assert token != stored.token_digest
        assert len(stored.token_digest) == 64
        assert session_user(db, token).id == user.id


def test_expired_session_is_rejected_and_deleted():
    factory = session_factory()
    with factory() as db:
        user = add_user(db)
        now = datetime.now(UTC)
        token = create_session(db, user.id, now=now - timedelta(days=31))
        assert session_user(db, token, now=now) is None
        assert db.scalar(select(AuthSession)) is None


def test_revoke_session_and_all_sessions():
    factory = session_factory()
    with factory() as db:
        user = add_user(db)
        first = create_session(db, user.id)
        second = create_session(db, user.id)
        revoke_session(db, first)
        assert session_user(db, first) is None
        assert session_user(db, second).id == user.id
        revoke_all_sessions(db, user.id)
        assert session_user(db, second) is None


def test_login_limiter_blocks_after_five_failures_and_clear_resets():
    limiter = LoginLimiter(max_failures=5, window_seconds=300)
    for _ in range(5):
        limiter.record_failure("192.0.2.10")
    assert limiter.is_blocked("192.0.2.10")
    limiter.clear("192.0.2.10")
    assert not limiter.is_blocked("192.0.2.10")
