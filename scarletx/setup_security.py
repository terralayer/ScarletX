from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

_LOCK = threading.RLock()


def _token_file() -> Path:
    return Path(os.getenv("SCARLETX_SETUP_TOKEN_FILE", ".scarletx-setup-token.json")).expanduser()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _write_digest(token: str) -> None:
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"sha256": _digest(token)}), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(path)
    os.chmod(path, 0o600)


def ensure_setup_token(*, admin_exists: bool) -> str | None:
    """Create the one-time first-run token and return it for startup logging."""
    with _LOCK:
        if admin_exists:
            consume_setup_token()
            return None
        token = os.getenv("SCARLETX_SETUP_TOKEN", "").strip() or secrets.token_urlsafe(32)
        # Regenerate on every pre-setup process start so a lost log token never
        # permanently locks the installation. Only the digest is persisted.
        _write_digest(token)
        return token


def verify_setup_token(value: str) -> bool:
    candidate = (value or "").strip()
    if not candidate:
        return False
    with _LOCK:
        path = _token_file()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected = str(payload.get("sha256") or "")
        except (OSError, ValueError, TypeError):
            return False
        return bool(expected and hmac.compare_digest(_digest(candidate), expected))


def consume_setup_token() -> None:
    with _LOCK:
        try:
            _token_file().unlink(missing_ok=True)
        except OSError:
            pass
