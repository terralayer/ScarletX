from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"required patch marker not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, *, minimum: int = 1) -> None:
    text = read(path)
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"required patch marker not found enough times in {path}: {old[:120]!r} ({count})")
    write(path, text.replace(old, new))


write(
    "scarletx/setup_security.py",
    '''from __future__ import annotations

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
''',
)

write(
    "scarletx/secret_store.py",
    '''from __future__ import annotations

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
                handle.write(key + b"\\n")
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
''',
)

write(
    "scarletx/archive_security.py",
    '''from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

_DRIVE = re.compile(r"^[A-Za-z]:")


def validate_archive_member_path(name: str) -> PurePosixPath:
    raw = str(name or "").replace("\\\\", "/").strip()
    if not raw or raw.startswith("/") or _DRIVE.match(raw):
        raise ValueError("archive member path is absolute or empty")
    path = PurePosixPath(raw)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("archive member path contains traversal components")
    return path


def parse_7z_listing(output: str) -> list[str]:
    members: list[str] = []
    in_entries = False
    for line in (output or "").splitlines():
        if line.strip().startswith("----------"):
            in_entries = True
            continue
        if in_entries and line.startswith("Path = "):
            name = line[7:].strip()
            validate_archive_member_path(name)
            members.append(name)
    return members


def validate_extracted_tree(root: Path) -> None:
    base = root.resolve()
    for item in root.rglob("*"):
        if item.is_symlink():
            raise ValueError(f"archive extracted a symbolic link: {item.name}")
        resolved = item.resolve(strict=False)
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"archive extraction escaped quarantine: {item}") from exc
''',
)

write(
    "scarletx/library_match.py",
    '''from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def normalize_title(value: str) -> str:
    value = Path(str(value or "")).stem.casefold()
    value = re.sub(r"\\[[^\\]]*\\]|\\([^)]*\\)", " ", value)
    value = re.sub(r"['’ʼ]", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


@dataclass(frozen=True)
class SceneMatchIndex:
    exact: dict[str, tuple]
    anchors: dict[str, tuple]


def build_scene_match_index(scenes) -> SceneMatchIndex:
    exact: dict[str, list] = {}
    anchors: dict[str, list] = {}
    for scene in scenes:
        title = normalize_title(scene.title)
        if len(title) < 4:
            continue
        exact.setdefault(title, []).append(scene)
        words = title.split()
        if words:
            anchor = max(words, key=lambda word: (len(word), word))
            anchors.setdefault(anchor, []).append((title, scene))
    return SceneMatchIndex(
        exact={key: tuple(value) for key, value in exact.items()},
        anchors={key: tuple(value) for key, value in anchors.items()},
    )


def match_local_scene(path: Path, index: SceneMatchIndex):
    stem = normalize_title(path.name)
    exact = index.exact.get(stem, ())
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    candidates: dict[int, tuple[int, object]] = {}
    for token in set(stem.split()):
        for title, scene in index.anchors.get(token, ()):
            if title in stem:
                candidates[id(scene)] = (len(title), scene)
    if not candidates:
        return None
    ranked = sorted(candidates.values(), key=lambda item: item[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None
    return ranked[0][1]
''',
)

# Setup schema keeps the reusable account-update payload free of the one-time token.
replace_once(
    "scarletx/schemas.py",
    '''class AdminSetupWrite(BaseModel):
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    password_confirm: str = Field(min_length=12, max_length=1024)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        return self


class LoginWrite(BaseModel):''',
    '''class AdminCredentialsWrite(BaseModel):
    username: str = Field(default="admin", min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=1024)
    password_confirm: str = Field(min_length=12, max_length=1024)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required")
        return value

    @model_validator(mode="after")
    def passwords_match(self):
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        return self


class AdminSetupWrite(AdminCredentialsWrite):
    setup_token: str = Field(min_length=16, max_length=512)


class LoginWrite(BaseModel):''',
)
replace_once("scarletx/schemas.py", "\n\nclass AdminCredentialsWrite(AdminSetupWrite):\n    pass\n", "\n")

# Session lookup uses one joined SELECT.
replace_once(
    "scarletx/auth.py",
    '''    row = db.scalar(
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
    return user''',
    '''    result = db.execute(
        select(AuthSession, AuthUser)
        .join(AuthUser, AuthUser.id == AuthSession.user_id)
        .where(AuthSession.token_digest == _digest(token))
        .limit(1)
    ).first()
    if result is None:
        return None
    row, user = result
    if _as_utc(row.expires_at) <= now:
        db.delete(row)
        db.commit()
        return None

    last_seen = _as_utc(row.last_seen_at)
    if now - last_seen >= SESSION_TOUCH_INTERVAL:
        row.last_seen_at = now
        db.commit()
    return user''',
)

# API keys are header-only and auth middleware avoids a guaranteed admin-exists query.
replace_once(
    "scarletx/http_security.py",
    'from sqlalchemy import select\n',
    '',
)
replace_once("scarletx/http_security.py", 'from .models import AuthUser\n', '')
replace_once(
    "scarletx/http_security.py",
    '''def _supplied_api_key(request: Request) -> str:
    supplied = request.headers.get("X-Api-Key") or request.query_params.get("apikey") or ""
    authorization = request.headers.get("Authorization") or ""
''',
    '''def _supplied_api_key(request: Request) -> str:
    supplied = request.headers.get("X-Api-Key") or ""
    authorization = request.headers.get("Authorization") or ""
''',
)
replace_once(
    "scarletx/http_security.py",
    '''            with session_factory() as db:
                admin_exists = db.scalar(select(AuthUser.id).limit(1)) is not None
                if not admin_exists:
                    return JSONResponse(
                        {"detail": "Administrator setup is required"},
                        status_code=401,
                    )

                token = request.cookies.get(SESSION_COOKIE_NAME) or ""
''',
    '''            with session_factory() as db:
                token = request.cookies.get(SESSION_COOKIE_NAME) or ""
''',
)

# Enforce/consume the one-time setup token.
replace_once(
    "scarletx/auth_routes.py",
    'from .models import AuthUser\n',
    'from .models import AuthUser\nfrom .setup_security import consume_setup_token, verify_setup_token\n',
)
replace_once(
    "scarletx/auth_routes.py",
    '''    if _admin_exists(db):
        raise HTTPException(409, "Administrator already configured")

    user = AuthUser(''',
    '''    if _admin_exists(db):
        raise HTTPException(409, "Administrator already configured")
    if not verify_setup_token(payload.setup_token):
        raise HTTPException(403, "Invalid or expired first-run setup token")

    user = AuthUser(''',
)
replace_once(
    "scarletx/auth_routes.py",
    '''    token = create_session(db, user.id)
    _set_session_cookie(response, request, token)
    return {"username": user.username}
''',
    '''    token = create_session(db, user.id)
    consume_setup_token()
    _set_session_cookie(response, request, token)
    return {"username": user.username}
''',
)

# Browser first-run form collects the token shown in backend logs.
replace_once(
    "frontend/auth.js",
    '''        <div class="sx-auth-field"><label for="authUsername">Username</label><input id="authUsername" name="username" autocomplete="username" maxlength="100" required></div>
        <div class="sx-auth-field"><label for="authPassword">Password</label>''',
    '''        <div class="sx-auth-field"><label for="authUsername">Username</label><input id="authUsername" name="username" autocomplete="username" maxlength="100" required></div>
        <div class="sx-auth-field" id="authSetupTokenField" hidden><label for="authSetupToken">First-run setup token</label><input id="authSetupToken" name="setup_token" autocomplete="off" maxlength="512"><span class="sx-auth-hint">Copy the token printed in the ScarletX backend startup log.</span></div>
        <div class="sx-auth-field"><label for="authPassword">Password</label>''',
)
replace_once(
    "frontend/auth.js",
    '''    el('authConfirmField').hidden = !setup;
    el('authPasswordConfirm').required = setup;
''',
    '''    el('authSetupTokenField').hidden = !setup;
    el('authSetupToken').required = setup;
    el('authConfirmField').hidden = !setup;
    el('authPasswordConfirm').required = setup;
''',
)
replace_once(
    "frontend/auth.js",
    '''    el('authPassword').value = '';
    el('authPasswordConfirm').value = '';
''',
    '''    el('authSetupToken').value = '';
    el('authPassword').value = '';
    el('authPasswordConfirm').value = '';
''',
)
replace_once(
    "frontend/auth.js",
    '''        const passwordConfirm = el('authPasswordConfirm').value;
        if (password.length < 12) throw new Error('Password must be at least 12 characters.');
        if (password !== passwordConfirm) throw new Error('Passwords do not match.');
        await request('/api/setup/admin', {method:'POST', body:JSON.stringify({username, password, password_confirm:passwordConfirm})});
''',
    '''        const setupToken = el('authSetupToken').value.trim();
        const passwordConfirm = el('authPasswordConfirm').value;
        if (!setupToken) throw new Error('The first-run setup token is required.');
        if (password.length < 12) throw new Error('Password must be at least 12 characters.');
        if (password !== passwordConfirm) throw new Error('Passwords do not match.');
        await request('/api/setup/admin', {method:'POST', body:JSON.stringify({username, password, password_confirm:passwordConfirm, setup_token:setupToken})});
''',
)

# Startup creates/logs the one-time token only while no admin exists.
replace_once(
    "scarletx/main.py",
    '    BackgroundJob, BackupRecord, History, IndexerFeedItem, LibraryItemConfig,\n',
    '    AuthUser, BackgroundJob, BackupRecord, History, IndexerFeedItem, LibraryItemConfig,\n',
)
replace_once(
    "scarletx/main.py",
    'from .settings_store import load_database_settings, seed_database_settings, set_setting\n',
    'from .settings_store import load_database_settings, seed_database_settings, set_setting\nfrom .setup_security import ensure_setup_token\n',
)
replace_once(
    "scarletx/main.py",
    '''        seed_database_settings(db)
        migrate_to_scarletx(db)
        seed_quality_profiles(db)
''',
    '''        seed_database_settings(db)
        migrate_to_scarletx(db)
        setup_token = ensure_setup_token(admin_exists=db.scalar(select(AuthUser.id).limit(1)) is not None)
        if setup_token:
            print(f"ScarletX first-run setup token: {setup_token}", flush=True)
        seed_quality_profiles(db)
''',
)

# Cryptography is a runtime dependency because secrets are encrypted at rest.
replace_once(
    "pyproject.toml",
    '  "pwdlib[argon2]>=0.2,<1",\n',
    '  "pwdlib[argon2]>=0.2,<1",\n  "cryptography>=43,<48",\n',
)
replace_once(
    "requirements.txt",
    'pwdlib[argon2]>=0.2,<1\n',
    'pwdlib[argon2]>=0.2,<1\ncryptography>=43,<48\n',
)

# Encrypt AppSetting secret rows transparently, including legacy plaintext migration.
replace_once(
    "scarletx/settings_store.py",
    'from .models import AppSetting\n',
    'from .models import AppSetting\nfrom .secret_store import decrypt_secret, encrypt_secret, migrate_secret\n',
)
replace_once(
    "scarletx/settings_store.py",
    '''def invalidate_settings_cache(db=None):
    with _SETTINGS_CACHE_LOCK:
        if db is None: _SETTINGS_CACHE.clear()
        else: _SETTINGS_CACHE.pop(_cache_key(db), None)

LEGACY_KEYS={''',
    '''def invalidate_settings_cache(db=None):
    with _SETTINGS_CACHE_LOCK:
        if db is None: _SETTINGS_CACHE.clear()
        else: _SETTINGS_CACHE.pop(_cache_key(db), None)

def _setting_value(item):
    if item is None:
        return ""
    return decrypt_secret(item.value) if item.is_secret else item.value

LEGACY_KEYS={''',
)
replace_once(
    "scarletx/settings_store.py",
    '''def set_setting(db,key,value,*,commit=True):
    item=db.get(AppSetting,key)
    if item is None:
        item=AppSetting(key=key,value=value,is_secret=key in SECRET_KEYS);db.add(item)
    else:
        item.value=value;item.is_secret=key in SECRET_KEYS
    if commit: db.commit()
    invalidate_settings_cache(db)
''',
    '''def set_setting(db,key,value,*,commit=True):
    is_secret=key in SECRET_KEYS
    stored=encrypt_secret(value) if is_secret else value
    item=db.get(AppSetting,key)
    if item is None:
        item=AppSetting(key=key,value=stored,is_secret=is_secret);db.add(item)
    else:
        item.value=stored;item.is_secret=is_secret
    if commit: db.commit()
    invalidate_settings_cache(db)
''',
)
replace_once("scarletx/settings_store.py", 'not (item.value or "").strip() and value', 'not (_setting_value(item) or "").strip() and value')
replace_once("scarletx/settings_store.py", '            item.value = value\n            item.is_secret = True\n', '            item.value = encrypt_secret(value)\n            item.is_secret = True\n')
replace_all("scarletx/settings_store.py", 'json.loads(item.value if item else "[]")', 'json.loads(_setting_value(item) if item else "[]")', minimum=5)
replace_once("scarletx/settings_store.py", 'json.loads(idx.value or "[]")', 'json.loads(_setting_value(idx) or "[]")')
replace_once("scarletx/settings_store.py", '        idx.value=json.dumps(clean)\n', '        idx.value=encrypt_secret(json.dumps(clean))\n')
replace_once("scarletx/settings_store.py", 'json.loads(provider_item.value if provider_item else "[]")', 'json.loads(_setting_value(provider_item) if provider_item else "[]")')
replace_once(
    "scarletx/settings_store.py",
    '    d=Settings(); v=default_setting_values();v.update({x.key:x.value for x in db.query(AppSetting).all()})\n',
    '''    d=Settings(); v=default_setting_values(); migrated=False
    for item in db.query(AppSetting).all():
        if item.is_secret:
            plain, stored = migrate_secret(item.value)
            v[item.key] = plain
            if stored != item.value:
                item.value = stored
                migrated = True
        else:
            v[item.key] = item.value
    if migrated:
        db.commit()
''',
)

# Archive safety: validated paths + quarantined external extraction.
replace_once(
    "scarletx/native_usenet.py",
    'import zipfile\n',
    'import zipfile\nfrom tempfile import TemporaryDirectory\n',
)
replace_once(
    "scarletx/native_usenet.py",
    'from .models import History, NativeUsenetJob, TrackedDownload, utcnow\n',
    'from .archive_security import parse_7z_listing, validate_archive_member_path, validate_extracted_tree\nfrom .models import History, NativeUsenetJob, TrackedDownload, utcnow\n',
)
replace_once(
    "scarletx/native_usenet.py",
    '''                    target = (archive.parent / member.filename).resolve()
                    try:
                        target.relative_to(root)
                    except ValueError as exc:
                        raise NativeUsenetError(f"Unsafe path in ZIP archive {archive.name}") from exc
''',
    '''                    try:
                        safe_member = validate_archive_member_path(member.filename)
                    except ValueError as exc:
                        raise NativeUsenetError(f"Unsafe path in ZIP archive {archive.name}") from exc
                    target = (archive.parent / Path(*safe_member.parts)).resolve()
                    try:
                        target.relative_to(root)
                    except ValueError as exc:
                        raise NativeUsenetError(f"Unsafe path in ZIP archive {archive.name}") from exc
''',
)
replace_once(
    "scarletx/native_usenet.py",
    '''    tools = _tool_status()
    for archive in [*rars, *sevens]:
        if _postprocess_cancelled(job_id):
            raise asyncio.CancelledError
        if archive.suffix.casefold() == ".rar" and tools["unrar"] and Path(tools["unrar"]).name == "unrar":
            password_arg = f"-p{password}" if password else "-p-"
            command = [tools["unrar"], "x", "-o+", "-y", password_arg, str(archive), str(archive.parent) + "/"]
        elif tools["7z"]:
            command = [tools["7z"], "x", "-y"]
            if password:
                command.append(f"-p{password}")
            command.extend([f"-o{archive.parent}", str(archive)])
        else:
            raise NativeUsenetError("RAR/7z archive downloaded but neither unrar nor 7z is installed")
        result = _run_tool(command, archive.parent, 600, job_id=job_id, label=f"Extracting {archive.name}")
        if result.returncode != 0:
            raise NativeUsenetError(f"Could not unpack {archive.name}: {(result.stdout or '')[-1200:]}")
        notes.append(f"Extracted {archive.name}")
''',
    '''    tools = _tool_status()
    archive_tool = tools["7z"]
    if not archive_tool:
        raise NativeUsenetError("Secure RAR/7z extraction requires 7z")
    for archive in [*rars, *sevens]:
        if _postprocess_cancelled(job_id):
            raise asyncio.CancelledError
        listing = [archive_tool, "l", "-slt"]
        if password:
            listing.append(f"-p{password}")
        listing.append(str(archive))
        listed = _run_tool(listing, archive.parent, 120, job_id=job_id, label=f"Listing {archive.name}")
        if listed.returncode != 0:
            raise NativeUsenetError(f"Could not inspect {archive.name}: {(listed.stdout or '')[-1200:]}")
        try:
            members = parse_7z_listing(listed.stdout or "")
        except ValueError as exc:
            raise NativeUsenetError(f"Unsafe path in archive {archive.name}: {exc}") from exc
        if not members:
            raise NativeUsenetError(f"Archive {archive.name} contains no safely listable members")
        with TemporaryDirectory(prefix=".scarletx-extract-", dir=archive.parent) as temp_dir:
            quarantine = Path(temp_dir)
            command = [archive_tool, "x", "-y"]
            if password:
                command.append(f"-p{password}")
            command.extend([f"-o{quarantine}", str(archive)])
            result = _run_tool(command, archive.parent, 600, job_id=job_id, label=f"Extracting {archive.name}")
            if result.returncode != 0:
                raise NativeUsenetError(f"Could not unpack {archive.name}: {(result.stdout or '')[-1200:]}")
            try:
                validate_extracted_tree(quarantine)
            except ValueError as exc:
                raise NativeUsenetError(f"Unsafe extracted content in {archive.name}: {exc}") from exc
            for child in quarantine.iterdir():
                target = archive.parent / child.name
                target = _unique_directory(target) if child.is_dir() else _unique_file_path(target)
                shutil.move(str(child), str(target))
        notes.append(f"Extracted {archive.name}")
''',
)
replace_once(
    "scarletx/native_usenet.py",
    'status="failed", error="No enabled Usenet provider is configured", completed_at=utcnow())',
    'status="failed", error="No enabled Usenet provider is configured", completed_at=utcnow(), unpack_password=None)',
)
replace_once(
    "scarletx/native_usenet.py",
    '''        completed_at=utcnow(),
    )
    with session_factory() as db:
        refreshed = db.get(NativeUsenetJob, job_id)
''',
    '''        completed_at=utcnow(),
        unpack_password=None,
    )
    with session_factory() as db:
        refreshed = db.get(NativeUsenetJob, job_id)
''',
)
replace_once(
    "scarletx/native_usenet.py",
    '''                completed_at=utcnow(),
            )
            _clear_live_progress(job_id)
''',
    '''                completed_at=utcnow(),
                unpack_password=None,
            )
            _clear_live_progress(job_id)
''',
)
replace_once(
    "scarletx/native_usenet.py",
    'status="cancelled", speed_bps=0.0, eta_seconds=0, output_path=None, error=None, completed_at=utcnow())',
    'status="cancelled", speed_bps=0.0, eta_seconds=0, output_path=None, error=None, completed_at=utcnow(), unpack_password=None)',
)
replace_once(
    "scarletx/native_usenet.py",
    'status="failed", error=message, speed_bps=0.0, eta_seconds=0, output_path=failed_path, completed_at=utcnow())',
    'status="failed", error=message, speed_bps=0.0, eta_seconds=0, output_path=failed_path, completed_at=utcnow(), unpack_password=None)',
)

# Nginx owns public HTTP security and compression.
write(
    "nginx/scarletx.conf",
    '''server {
    listen ${SCARLETX_WEB_PORT};
    server_name _;
    server_tokens off;

    root /usr/share/nginx/html;
    index index.html;

    client_max_body_size 100m;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_comp_level 5;
    gzip_types text/plain text/css application/json application/javascript application/xml image/svg+xml;

    proxy_hide_header X-Content-Type-Options;
    proxy_hide_header Referrer-Policy;
    proxy_hide_header X-Frame-Options;
    proxy_hide_header Permissions-Policy;
    proxy_hide_header Content-Security-Policy;

    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header X-Frame-Options "DENY" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; connect-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'" always;

    location = /api/activity/stream {
        proxy_pass http://scarletx-backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${SCARLETX_FORWARDED_PROTO};
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location /api/ {
        proxy_pass http://scarletx-backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${SCARLETX_FORWARDED_PROTO};
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location = /docs {
        proxy_pass http://scarletx-backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${SCARLETX_FORWARDED_PROTO};
    }

    location = /redoc {
        proxy_pass http://scarletx-backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${SCARLETX_FORWARDED_PROTO};
    }

    location = /openapi.json {
        proxy_pass http://scarletx-backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto ${SCARLETX_FORWARDED_PROTO};
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
''',
)

# Backend image runs non-root and keeps security material under /config.
replace_once(
    "Dockerfile",
    '    SCARLETX_DEFAULT_MEDIA_ROOT=/tmp\n',
    '    SCARLETX_DEFAULT_MEDIA_ROOT=/tmp \\\n    SCARLETX_SECRET_KEY_FILE=/config/.scarletx-secret.key \\\n    SCARLETX_SETUP_TOKEN_FILE=/config/setup-token.json\n',
)
replace_once(
    "Dockerfile",
    'WORKDIR /app\n\nRUN set -eux; \\\n',
    'WORKDIR /app\n\nRUN groupadd --gid 568 scarletx && useradd --uid 568 --gid 568 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin scarletx\n\nRUN set -eux; \\\n',
)
replace_once(
    "Dockerfile",
    'RUN mkdir -p /config /config/generated /config/cache /downloads/incomplete /downloads/complete /downloads/failed /media /backups\n\nVOLUME',
    'RUN mkdir -p /config /config/generated /config/cache /downloads/incomplete /downloads/complete /downloads/failed /media /backups \\\n    && chown -R 568:568 /config /downloads /media /backups\n\nVOLUME',
)
replace_once("Dockerfile", 'EXPOSE 8000\n\nHEALTHCHECK', 'EXPOSE 8000\nUSER 568:568\n\nHEALTHCHECK')
replace_once("Dockerfile.web", 'ENV SCARLETX_WEB_PORT=8690\n', 'ENV SCARLETX_WEB_PORT=8690 \\\n    SCARLETX_FORWARDED_PROTO=http\n')

# Deployment paths explicitly control the externally visible scheme.
replace_once(
    "docker-compose.yml",
    '    environment:\n      SCARLETX_WEB_PORT: "8690"\n',
    '    environment:\n      SCARLETX_WEB_PORT: "8690"\n      SCARLETX_FORWARDED_PROTO: ${SCARLETX_FORWARDED_PROTO:-http}\n',
)
replace_once(
    "docker-compose.truenas.yml",
    '    environment:\n      SCARLETX_WEB_PORT: ${SCARLETX_PORT:-8690}\n',
    '    environment:\n      SCARLETX_WEB_PORT: ${SCARLETX_PORT:-8690}\n      SCARLETX_FORWARDED_PROTO: ${SCARLETX_FORWARDED_PROTO:-http}\n',
)
replace_once(
    "packaging/truenas/scarletx/templates/docker-compose.yaml",
    '{% do web.environment.add_env("SCARLETX_WEB_PORT", values.network.web_port.port_number) %}\n',
    '{% do web.environment.add_env("SCARLETX_WEB_PORT", values.network.web_port.port_number) %}\n{% do web.environment.add_env("SCARLETX_FORWARDED_PROTO", "http") %}\n',
)

# SQLite memory/concurrency bounds.
replace_once("scarletx/db.py", 'kwargs.update(pool_size=10, max_overflow=20, pool_timeout=30)', 'kwargs.update(pool_size=5, max_overflow=5, pool_timeout=30)')
replace_once("scarletx/db.py", 'cursor.execute("PRAGMA cache_size=-65536")', 'cursor.execute("PRAGMA cache_size=-16384")')
replace_once("scarletx/db.py", 'cursor.execute("PRAGMA mmap_size=268435456")', 'cursor.execute("PRAGMA mmap_size=134217728")')

# Indexed library matching and bulk probe lookup.
replace_once(
    "scarletx/media_library.py",
    'from .models import (\n',
    'from .library_match import build_scene_match_index, match_local_scene\nfrom .models import (\n',
)
replace_once(
    "scarletx/media_library.py",
    '        scenes = db.scalars(select(Scene).where(Scene.content_type == "scene")).all()\n        known =',
    '        scenes = db.scalars(select(Scene).where(Scene.content_type == "scene")).all()\n        scene_match_index = build_scene_match_index(scenes)\n        probe_map = {probe.media_file_id: probe for probe in db.scalars(select(MediaProbe)).all()}\n        known =',
)
replace_once("scarletx/media_library.py", 'scene = _match_local_scene(path, scenes)', 'scene = match_local_scene(path, scene_match_index)')
replace_once(
    "scarletx/media_library.py",
    '                    probe = db.get(MediaProbe, media.id)\n                    if probe and probe.file_mtime == stat.st_mtime',
    '                    probe = probe_map.get(media.id)\n                    if probe and probe.file_mtime == stat.st_mtime',
)
replace_once(
    "scarletx/media_library.py",
    '''                probe = db.get(MediaProbe, media.id)
                if probe is None:
                    probe = MediaProbe(media_file_id=media.id)
                    db.add(probe)
''',
    '''                probe = probe_map.get(media.id)
                if probe is None:
                    probe = MediaProbe(media_file_id=media.id)
                    db.add(probe)
                    probe_map[media.id] = probe
''',
)

# Batch download metadata/native state and group non-terminal commits.
replace_once(
    "scarletx/download_processing.py",
    '''def _native_states(db, jobs):
    states = {}
    for job in jobs:
        native = db.get(NativeUsenetJob, job["external_id"])
        if not native:
            continue
        status = native.status
        states[job["tracked_id"]] = {
            "client": "scarletx",
            "status": status,
            "completed": status == "completed",
            "failed": status in {"failed", "cancelled"},
            "path": native.output_path,
            "error": native.error or ("Download was cancelled" if status == "cancelled" else ""),
        }
    return states
''',
    '''def _pending_state_maps(db, pending):
    tracked_ids = [tracked.id for tracked in pending]
    external_ids = [tracked.nzo_id for tracked in pending if tracked.nzo_id]
    metadata_by_tracked = {
        row.tracked_download_id: row
        for row in db.scalars(
            select(TrackedDownloadMeta).where(TrackedDownloadMeta.tracked_download_id.in_(tracked_ids))
        ).all()
    } if tracked_ids else {}
    native_by_id = {
        row.id: row
        for row in db.scalars(
            select(NativeUsenetJob).where(NativeUsenetJob.id.in_(external_ids))
        ).all()
    } if external_ids else {}
    jobs = []
    states = {}
    for tracked in pending:
        jobs.append({"tracked_id": tracked.id, "external_id": tracked.nzo_id, "client": "scarletx"})
        native = native_by_id.get(tracked.nzo_id)
        if native is None:
            continue
        status = native.status
        states[tracked.id] = {
            "client": "scarletx",
            "status": status,
            "completed": status == "completed",
            "failed": status in {"failed", "cancelled"},
            "path": native.output_path,
            "error": native.error or ("Download was cancelled" if status == "cancelled" else ""),
        }
    return jobs, states, metadata_by_tracked, native_by_id
''',
)
replace_once(
    "scarletx/download_processing.py",
    '''    with session_factory() as db:
        pending = db.scalars(select(TrackedDownload).where(TrackedDownload.status.in_(PENDING))).all()
        jobs = []
        for tracked in pending:
            meta = db.get(TrackedDownloadMeta, tracked.id)
            jobs.append(
                {
                    "tracked_id": tracked.id,
                    "external_id": tracked.nzo_id,
                    "client": "scarletx",
                }
            )
        native_jobs = [item for item in jobs if item["client"] == "scarletx"]
        states = _native_states(db, native_jobs)
''',
    '''    with session_factory() as db:
        pending = db.scalars(select(TrackedDownload).where(TrackedDownload.status.in_(PENDING))).all()
        jobs, states, metadata_by_tracked, native_by_id = _pending_state_maps(db, pending)
''',
)
replace_once(
    "scarletx/download_processing.py",
    '''    imported = failed = 0
    notifications = []
    for job in jobs:
        state = states.get(job["tracked_id"])
        if not state:
            continue
        with session_factory() as db:
            tracked = db.get(TrackedDownload, job["tracked_id"])
            meta = db.get(TrackedDownloadMeta, tracked.id) if tracked else None
            if not tracked:
                continue
            tracked.client_status = state["status"]
            tracked.last_checked_at = utcnow()
            if state["failed"]:
                tracked.status = "failed"
                tracked.error = state["error"] or f"Download status: {state['status']}"
                _block_failed(db, tracked, meta, tracked.error)
                db.add(History(event_type="download_failed", scene_id=tracked.scene_id, message=f"Download failed: {tracked.release_title}"))
                db.commit()
                failed += 1
                notifications.append(("failed", {"scene_id": tracked.scene_id, "release_title": tracked.release_title, "error": tracked.error}))
                continue
            if not state["completed"]:
                tracked.status = "downloading" if state["status"] not in {"queued", "paused"} else state["status"]
                db.commit()
                continue
            storage_path = state["path"]
            tracked.storage_path = storage_path
            tracked.status = "import_pending"
            tracked.completed_at = tracked.completed_at or utcnow()
            metadata_id = tracked.scene_tpdb_id
            local_scene = db.get(Scene, tracked.scene_id) if tracked.scene_id else None
            release_title = tracked.release_title
            download_client = state["client"]
            db.commit()

        try:
''',
    '''    imported = failed = 0
    notifications = []
    completed_jobs = []
    tracked_ids = [job["tracked_id"] for job in jobs]
    with session_factory() as db:
        tracked_by_id = {
            row.id: row for row in db.scalars(
                select(TrackedDownload).where(TrackedDownload.id.in_(tracked_ids))
            ).all()
        } if tracked_ids else {}
        for job in jobs:
            state = states.get(job["tracked_id"])
            tracked = tracked_by_id.get(job["tracked_id"])
            if not state or not tracked:
                continue
            tracked.client_status = state["status"]
            tracked.last_checked_at = utcnow()
            if state["failed"]:
                tracked.status = "failed"
                tracked.error = state["error"] or f"Download status: {state['status']}"
                _block_failed(db, tracked, metadata_by_tracked.get(tracked.id), tracked.error)
                db.add(History(event_type="download_failed", scene_id=tracked.scene_id, message=f"Download failed: {tracked.release_title}"))
                failed += 1
                notifications.append(("failed", {"scene_id": tracked.scene_id, "release_title": tracked.release_title, "error": tracked.error}))
                continue
            if not state["completed"]:
                tracked.status = "downloading" if state["status"] not in {"queued", "paused"} else state["status"]
                continue
            completed_jobs.append(job)
        db.commit()

    for job in completed_jobs:
        state = states[job["tracked_id"]]
        with session_factory() as db:
            tracked = db.get(TrackedDownload, job["tracked_id"])
            if not tracked:
                continue
            storage_path = state["path"]
            tracked.storage_path = storage_path
            tracked.status = "import_pending"
            tracked.completed_at = tracked.completed_at or utcnow()
            metadata_id = tracked.scene_tpdb_id
            local_scene = db.get(Scene, tracked.scene_id) if tracked.scene_id else None
            release_title = tracked.release_title
            download_client = state["client"]
            db.commit()

        try:
''',
)

# Supply-chain workflow changes are committed separately through the GitHub connector.
write(
    ".github/dependabot.yml",
    '''version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10
''',
)

# Keep locally generated security files out of source control.
gitignore = read(".gitignore")
for item in (".scarletx-secret.key", ".scarletx-setup-token.json", "setup-token.json"):
    if item not in gitignore.splitlines():
        gitignore += ("\n" if gitignore and not gitignore.endswith("\n") else "") + item + "\n"
write(".gitignore", gitignore)

# Remove this one-shot implementation helper and workflow from the resulting tree.
(ROOT / "tools/apply_039_hardening.py").unlink(missing_ok=True)
