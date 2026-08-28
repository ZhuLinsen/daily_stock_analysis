# -*- coding: utf-8 -*-
"""
Web admin authentication module.

Single toggle (ADMIN_AUTH_ENABLED) + file-based credentials.
First login sets initial password; supports web change-password and CLI reset.
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from dotenv import dotenv_values

logger = logging.getLogger(__name__)

COOKIE_NAME = "dsa_session"
LEGACY_PBKDF2_ITERATIONS = 100_000
PBKDF2_ITERATIONS = 600_000
PASSWORD_HASH_VERSION = "v2"
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
RATE_LIMIT_WINDOW_SEC = 300
RATE_LIMIT_MAX_FAILURES = 5
SESSION_MAX_AGE_HOURS_DEFAULT = 24
MIN_PASSWORD_LEN = 10
DOCKER_PUBLISHED_HOST_BIND_IP_ENV = "DSA_DOCKER_PUBLISHED_HOST_BIND_IP"

# Lazy-loaded state
_auth_enabled: Optional[bool] = None
_session_secret: Optional[bytes] = None
_password_hash_salt: Optional[bytes] = None
_password_hash_stored: Optional[bytes] = None
_password_hash_iterations: Optional[int] = None
_password_hash_needs_upgrade: bool = False
_rate_limit: dict[str, Tuple[int, float]] = {}
_rate_limit_lock = None


def _get_lock():
    """Lazy init threading lock for rate limit dict."""
    global _rate_limit_lock
    if _rate_limit_lock is None:
        import threading
        _rate_limit_lock = threading.Lock()
    return _rate_limit_lock


def _ensure_env_loaded() -> None:
    """Ensure .env is loaded before reading config."""
    from src.config import setup_env
    setup_env()


def _get_data_dir() -> Path:
    """Return DATA_DIR as parent of DATABASE_PATH."""
    db_path = os.getenv("DATABASE_PATH", "./data/stock_analysis.db")
    return Path(db_path).resolve().parent


def _get_credential_path() -> Path:
    """Path to stored password hash file."""
    return _get_data_dir() / ".admin_password_hash"


def _is_auth_enabled_from_env() -> bool:
    """Read ADMIN_AUTH_ENABLED from .env file."""
    _ensure_env_loaded()
    env_file = os.getenv("ENV_FILE")
    env_path = Path(env_file) if env_file else Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return False
    values = dotenv_values(env_path)
    val = (values.get("ADMIN_AUTH_ENABLED") or "").strip().lower()
    return val in ("true", "1", "yes")


def rotate_session_secret() -> bool:
    """Rotate the session signing secret to invalidate all active sessions."""
    global _session_secret
    data_dir = _get_data_dir()
    secret_path = data_dir / ".session_secret"
    data_dir.mkdir(parents=True, exist_ok=True)
    new_secret = secrets.token_bytes(32)
    try:
        tmp_path = secret_path.with_suffix(".tmp")
        tmp_path.write_bytes(new_secret)
        tmp_path.chmod(0o600)
        tmp_path.replace(secret_path)
        _session_secret = new_secret
        logger.info("Session secret rotated successfully")
        return True
    except OSError as e:
        logger.error("Failed to rotate .session_secret: %s", e)
        return False


def _load_session_secret() -> Optional[bytes]:
    """Load or create session secret."""
    global _session_secret
    if _session_secret is not None:
        return _session_secret

    data_dir = _get_data_dir()
    secret_path = data_dir / ".session_secret"

    try:
        if secret_path.exists():
            _session_secret = secret_path.read_bytes()
            if len(_session_secret) != 32:
                logger.warning("Invalid .session_secret length, regenerating")
                _session_secret = None
                if rotate_session_secret():
                    return _session_secret
                return None
            return _session_secret

        data_dir.mkdir(parents=True, exist_ok=True)
        new_secret = secrets.token_bytes(32)
        try:
            with open(secret_path, "xb") as f:
                f.write(new_secret)
            secret_path.chmod(0o600)
        except FileExistsError:
            _session_secret = secret_path.read_bytes()
        else:
            _session_secret = new_secret
        return _session_secret
    except OSError as e:
        logger.error("Failed to create or read .session_secret: %s", e)
        return None


def _derive_password_hash(password: str, salt: bytes, iterations: int) -> bytes:
    """Derive a PBKDF2-SHA256 hash for the submitted password."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt=salt,
        iterations=iterations,
    )


def _serialize_password_hash(salt: bytes, stored_hash: bytes, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Serialize a versioned password hash record."""
    salt_b64 = base64.standard_b64encode(salt).decode("ascii")
    hash_b64 = base64.standard_b64encode(stored_hash).decode("ascii")
    return f"{PASSWORD_HASH_VERSION}${PASSWORD_HASH_SCHEME}${iterations}${salt_b64}${hash_b64}"


def _build_password_hash(password: str, iterations: int = PBKDF2_ITERATIONS) -> Tuple[bytes, bytes, str]:
    """Create salt, digest, and serialized content for a password."""
    salt = secrets.token_bytes(32)
    derived = _derive_password_hash(password, salt=salt, iterations=iterations)
    return salt, derived, _serialize_password_hash(salt, derived, iterations=iterations)


def _parse_password_hash(value: str) -> Optional[Tuple[bytes, bytes, int, bool]]:
    """Parse password hash content. Returns (salt, hash, iterations, needs_upgrade)."""
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    if raw.startswith(f"{PASSWORD_HASH_VERSION}$"):
        parts = raw.split("$")
        if len(parts) != 5:
            return None
        _, scheme, iterations_text, salt_b64, hash_b64 = parts
        if scheme != PASSWORD_HASH_SCHEME:
            return None
        try:
            iterations = int(iterations_text)
            salt = base64.standard_b64decode(salt_b64)
            stored_hash = base64.standard_b64decode(hash_b64)
        except (ValueError, TypeError):
            return None
        if iterations <= 0 or not salt or not stored_hash:
            return None
        return salt, stored_hash, iterations, iterations < PBKDF2_ITERATIONS

    if ":" not in raw:
        return None
    parts = raw.split(":", 1)
    if len(parts) != 2:
        return None
    try:
        salt_b64, hash_b64 = parts[0].strip(), parts[1].strip()
        salt = base64.standard_b64decode(salt_b64)
        stored_hash = base64.standard_b64decode(hash_b64)
        if salt and stored_hash:
            return (salt, stored_hash, LEGACY_PBKDF2_ITERATIONS, True)
    except (ValueError, TypeError):
        pass
    return None


def _verify_password_hash(submitted: str, salt: bytes, stored_hash: bytes, iterations: int) -> bool:
    """Verify submitted password against stored pbkdf2 hash."""
    computed = _derive_password_hash(submitted, salt=salt, iterations=iterations)
    return hmac.compare_digest(computed, stored_hash)


def _load_credential_from_file() -> bool:
    """Load credential from file into module globals. Returns True if loaded."""
    global _password_hash_salt, _password_hash_stored, _password_hash_iterations, _password_hash_needs_upgrade

    path = _get_credential_path()
    if not path.exists():
        _password_hash_salt = None
        _password_hash_stored = None
        _password_hash_iterations = None
        _password_hash_needs_upgrade = False
        return False

    try:
        raw = path.read_text().strip()
        parsed = _parse_password_hash(raw)
        if parsed is None:
            logger.warning("Invalid .admin_password_hash format, ignoring")
            _password_hash_salt = None
            _password_hash_stored = None
            _password_hash_iterations = None
            _password_hash_needs_upgrade = False
            return False
        _password_hash_salt, _password_hash_stored, _password_hash_iterations, _password_hash_needs_upgrade = parsed
        return True
    except OSError as e:
        logger.error("Failed to read credential file: %s", e)
        return False


def refresh_auth_state() -> None:
    """Reload auth-related state from disk and env."""
    global _auth_enabled, _session_secret, _password_hash_iterations, _password_hash_needs_upgrade
    _auth_enabled = None
    _session_secret = None
    _password_hash_iterations = None
    _password_hash_needs_upgrade = False
    _load_credential_from_file()


def is_auth_enabled() -> bool:
    """Return whether admin authentication is enabled (ADMIN_AUTH_ENABLED=true)."""
    global _auth_enabled
    if _auth_enabled is not None:
        return _auth_enabled
    _auth_enabled = _is_auth_enabled_from_env()
    return _auth_enabled


def has_stored_password() -> bool:
    """Return whether a valid stored password hash exists on disk."""
    return _load_credential_from_file()


def _write_credential_content(content: str) -> Optional[str]:
    """Atomically write the credential file and refresh in-memory state."""
    data_dir = _get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    cred_path = _get_credential_path()
    try:
        tmp_path = cred_path.with_suffix(".tmp")
        tmp_path.write_text(content)
        tmp_path.chmod(0o600)
        tmp_path.replace(cred_path)
        _load_credential_from_file()
        return None
    except OSError as e:
        logger.error("Failed to write credential file: %s", e)
        return "密码保存失败"


def _store_password_hash(password: str, iterations: int = PBKDF2_ITERATIONS) -> Optional[str]:
    """Create and persist a credential hash for the given password."""
    _, _, content = _build_password_hash(password, iterations=iterations)
    return _write_credential_content(content)


def verify_stored_password(password: str) -> bool:
    """Verify password against stored credential even when auth is disabled."""
    if not has_stored_password():
        return False
    if not _verify_password_hash(
        password,
        _password_hash_salt,
        _password_hash_stored,
        _password_hash_iterations or LEGACY_PBKDF2_ITERATIONS,
    ):
        return False
    if _password_hash_needs_upgrade:
        err = _store_password_hash(password)
        if err:
            logger.warning("Failed to upgrade admin password hash after successful login")
    return True


def is_password_set() -> bool:
    """Return whether initial password has been set (credential file exists and valid)."""
    if not is_auth_enabled():
        return False
    return has_stored_password()


def is_password_changeable() -> bool:
    """Return whether password can be changed via web/CLI (always True when auth enabled)."""
    return is_auth_enabled()


def _get_session_secret() -> Optional[bytes]:
    """Return session signing secret."""
    if not is_auth_enabled():
        return None
    return _load_session_secret()


def _validate_password(pwd: str) -> Optional[str]:
    """Return error message if invalid, None if valid."""
    if not pwd or not pwd.strip():
        return "密码不能为空"
    if len(pwd) < MIN_PASSWORD_LEN:
        return f"密码至少 {MIN_PASSWORD_LEN} 位"
    return None


def set_initial_password(password: str) -> Optional[str]:
    """
    Set initial password (first-time setup). Returns error message or None on success.
    Atomic write with 0o600 permissions.
    """
    err = _validate_password(password)
    if err:
        return err
    return _store_password_hash(password)


def verify_password(password: str) -> bool:
    """Verify password against stored credential. Constant-time where applicable."""
    if not is_auth_enabled():
        return True
    return verify_stored_password(password)


def change_password(current: str, new: str) -> Optional[str]:
    """
    Change password. Verifies current, writes new hash. Returns error message or None on success.
    """
    if not is_auth_enabled():
        return "认证功能未启用"
    if not is_password_set():
        return "尚未设置密码"

    if not current or not current.strip():
        return "请输入当前密码"
    if not verify_stored_password(current):
        return "当前密码错误"

    err = _validate_password(new)
    if err:
        return err
    return _store_password_hash(new)


def create_session() -> str:
    """Create a signed session payload. Format: nonce.ts.signature."""
    secret = _get_session_secret()
    if not secret:
        return ""
    nonce = secrets.token_urlsafe(32)
    ts = str(int(time.time()))
    payload = f"{nonce}.{ts}"
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session(value: str) -> bool:
    """Verify session cookie and check expiry."""
    secret = _get_session_secret()
    if not secret or not value:
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    nonce, ts_str, sig = parts[0], parts[1], parts[2]
    payload = f"{nonce}.{ts_str}"
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    try:
        max_age_hours = int(os.getenv("ADMIN_SESSION_MAX_AGE_HOURS", str(SESSION_MAX_AGE_HOURS_DEFAULT)))
    except ValueError:
        max_age_hours = SESSION_MAX_AGE_HOURS_DEFAULT
    if time.time() - ts > max_age_hours * 3600:
        return False
    return True


def get_client_ip(request) -> str:
    """Get client IP, respecting TRUST_X_FORWARDED_FOR.

    When behind a single trusted reverse proxy, the proxy appends the real
    client IP as the rightmost entry in X-Forwarded-For.  We use [-1] instead
    of [0] so that an attacker cannot spoof an arbitrary leftmost value to
    rotate rate-limit buckets and bypass brute-force protection.
    """
    if os.getenv("TRUST_X_FORWARDED_FOR", "false").lower() == "true":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    if request.client:
        return request.client.host or "127.0.0.1"
    return "127.0.0.1"


def is_loopback_ip(value: str) -> bool:
    """Return True when ``value`` identifies a loopback host."""
    host = (value or "").strip()
    if not host:
        return False
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    return address.is_loopback


def _is_private_or_loopback_ip(value: str) -> bool:
    """Return True for local/private container-bridge source addresses."""
    host = (value or "").strip()
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if getattr(address, "ipv4_mapped", None):
        address = address.ipv4_mapped
    return address.is_loopback or address.is_private


def _is_compose_loopback_forwarded_request(request) -> bool:
    """Allow Docker bridge requests only when Compose published the host port to loopback."""
    published_bind_ip = os.getenv(DOCKER_PUBLISHED_HOST_BIND_IP_ENV, "")
    if not is_loopback_ip(published_bind_ip):
        return False
    if not request.client:
        return False
    return _is_private_or_loopback_ip(request.client.host or "")


def is_loopback_request(request) -> bool:
    """Return True for direct loopback or Docker bridge traffic published only on host loopback."""
    return is_loopback_ip(get_client_ip(request)) or _is_compose_loopback_forwarded_request(request)


def check_rate_limit(ip: str) -> bool:
    """Return True if under limit, False if rate limited."""
    lock = _get_lock()
    now = time.time()
    with lock:
        expired_keys = [k for k, (_, ts) in _rate_limit.items() if now - ts > RATE_LIMIT_WINDOW_SEC]
        for k in expired_keys:
            del _rate_limit[k]
        if ip in _rate_limit:
            count, first_ts = _rate_limit[ip]
            if count >= RATE_LIMIT_MAX_FAILURES:
                return False
        return True


def record_login_failure(ip: str) -> None:
    """Record a failed login attempt for rate limiting."""
    lock = _get_lock()
    now = time.time()
    with lock:
        if ip in _rate_limit:
            count, first_ts = _rate_limit[ip]
            if now - first_ts > RATE_LIMIT_WINDOW_SEC:
                _rate_limit[ip] = (1, now)
            else:
                _rate_limit[ip] = (count + 1, first_ts)
        else:
            _rate_limit[ip] = (1, now)


def clear_rate_limit(ip: str) -> None:
    """Clear rate limit for IP after successful login."""
    lock = _get_lock()
    with lock:
        _rate_limit.pop(ip, None)


def overwrite_password(new_password: str) -> Optional[str]:
    """
    Overwrite stored password without verifying current. For CLI reset only.
    Returns error message or None on success.
    """
    if not is_auth_enabled():
        return "认证功能未启用"
    err = _validate_password(new_password)
    if err:
        return err
    return _store_password_hash(new_password)


def reset_password_cli() -> int:
    """Interactive CLI to reset password. Returns exit code."""
    _ensure_env_loaded()
    if not _is_auth_enabled_from_env():
        print("Error: Auth is not enabled. Set ADMIN_AUTH_ENABLED=true in .env", file=sys.stderr)
        return 1

    print("Enter new admin password (will not echo):", end=" ")
    pwd = getpass.getpass("")
    err = _validate_password(pwd)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    print("Confirm new password:", end=" ")
    pwd2 = getpass.getpass("")
    if pwd != pwd2:
        print("Error: Passwords do not match", file=sys.stderr)
        return 1

    err = overwrite_password(pwd)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    print("Password has been reset successfully.")
    return 0


def _main() -> int:
    """CLI entry: reset_password subcommand."""
    if len(sys.argv) > 1 and sys.argv[1] == "reset_password":
        return reset_password_cli()
    print("Usage: python -m src.auth reset_password", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(_main())
