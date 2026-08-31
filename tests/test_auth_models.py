from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from scarletx.models import AuthSession, AuthUser
from scarletx.schemas import AdminSetupWrite, LoginWrite


def test_admin_setup_requires_12_character_password():
    with pytest.raises(ValidationError):
        AdminSetupWrite(username="admin", password="short", password_confirm="short")


def test_admin_setup_requires_matching_confirmation():
    with pytest.raises(ValidationError):
        AdminSetupWrite(
            username="admin",
            password="correct-horse-1",
            password_confirm="correct-horse-2",
        )


def test_login_schema_accepts_existing_credentials():
    request = LoginWrite(username="admin", password="correct-horse-battery")
    assert request.username == "admin"


def test_auth_models_hold_hashes_and_session_digests_only():
    user = AuthUser(
        username="Admin",
        username_normalized="admin",
        password_hash="$argon2id$example",
    )
    now = datetime.now(UTC)
    session = AuthSession(
        user_id=1,
        token_digest="a" * 64,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=30),
    )
    assert user.password_hash.startswith("$argon2id$")
    assert len(session.token_digest) == 64
