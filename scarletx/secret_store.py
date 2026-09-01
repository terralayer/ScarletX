from __future__ import annotations

import os
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"
_LOCK = threading.RLock()


class SecretStoreError(RuntimeError):
    pass


def _key_file() -> Path:
    return Path(os.getenv("SCARLETX_SECRET_KEY_FILE", ".scarletx-secret.key")).expanduser()


def _load_key() -> bytes:
    path = _key_file()
    with _LOCK:
        if path.exists():
            key = path.read_bytes().strip()
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return key
        path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        temp = path.with_name(path.name + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(temp, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(key + b"\n")
        except Exception:
            try:
                temp.unlink(missing_ok=True)
            finally:
                raise
        temp.replace(path)
        os.chmod(path, 0o600)
        return key


def _fernet() -> Fernet:
    try:
        return Fernet(_load_key())
    except (ValueError, OSError) as exc:
        raise SecretStoreError(f"ScarletX secret key is unavailable: {exc}") from exc


def encrypt_secret(value: str) -> str:
    plain = str(value or "")
    if not plain:
        return ""
    if plain.startswith(PREFIX):
        # Validate existing ciphertext instead of double-encrypting it.
        decrypt_secret(plain)
        return plain
    return PREFIX + _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    stored = str(value or "")
    if not stored or not stored.startswith(PREFIX):
        return stored
    try:
        return _fernet().decrypt(stored[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, OSError) as exc:
        raise SecretStoreError("ScarletX could not decrypt a stored secret; restore the matching installation key") from exc


def migrate_secret(value: str) -> tuple[str, str]:
    stored = str(value or "")
    plain = decrypt_secret(stored)
    if not plain:
        return "", ""
    encrypted = stored if stored.startswith(PREFIX) else encrypt_secret(plain)
    return plain, encrypted
