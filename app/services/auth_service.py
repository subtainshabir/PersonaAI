from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32

SESSION_COOKIE_NAME = "personaai_admin_session"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60  # 12 hours
SESSION_SALT = "personaai-admin-session"

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 5 * 60


class AuthConfigError(Exception):
    pass


class RateLimitedError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Too many failed attempts. Try again in {retry_after_seconds}s.")


def hash_password(plain_password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        plain_password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN,
    )
    return f"{salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    try:
        salt_hex, derived_hex = stored_hash.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(derived_hex)
    except (ValueError, AttributeError):
        return False

    candidate = hashlib.scrypt(
        plain_password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN,
    )
    return hmac.compare_digest(candidate, expected)


def _get_admin_username() -> str:
    username = os.environ.get("ADMIN_USERNAME")
    if not username:
        raise AuthConfigError("ADMIN_USERNAME is not configured in .env")
    return username


def _get_admin_password_hash() -> str:
    password_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if not password_hash:
        raise AuthConfigError("ADMIN_PASSWORD_HASH is not configured in .env")
    return password_hash


def _get_serializer() -> URLSafeTimedSerializer:
    secret_key = os.environ.get("SESSION_SECRET_KEY")
    if not secret_key:
        raise AuthConfigError("SESSION_SECRET_KEY is not configured in .env")
    return URLSafeTimedSerializer(secret_key)


def cookies_require_secure() -> bool:
    return os.environ.get("ADMIN_COOKIE_SECURE", "true").strip().lower() != "false"


# In-memory, single-process state. Restarting the app clears both, which
# means any outstanding session cookie stops working and failed-attempt
# counters reset — acceptable for a single-admin deployment.
_valid_session_ids: set[str] = set()
_failed_attempts: dict[str, tuple[int, float]] = {}  # ip -> (count, first_failure_ts)


def check_rate_limit(client_ip: str) -> None:
    entry = _failed_attempts.get(client_ip)
    if not entry:
        return
    count, first_failure_ts = entry
    if count < MAX_FAILED_ATTEMPTS:
        return
    elapsed = time.time() - first_failure_ts
    if elapsed < LOCKOUT_SECONDS:
        raise RateLimitedError(retry_after_seconds=int(LOCKOUT_SECONDS - elapsed))
    _failed_attempts.pop(client_ip, None)


def record_failed_attempt(client_ip: str) -> None:
    count, first_failure_ts = _failed_attempts.get(client_ip, (0, time.time()))
    _failed_attempts[client_ip] = (count + 1, first_failure_ts)


def record_successful_attempt(client_ip: str) -> None:
    _failed_attempts.pop(client_ip, None)


def verify_credentials(username: str, password: str) -> bool:
    try:
        expected_username = _get_admin_username()
        expected_hash = _get_admin_password_hash()
    except AuthConfigError:
        return False

    username_ok = hmac.compare_digest(username or "", expected_username)
    password_ok = verify_password(password or "", expected_hash)
    # Both checks always run so response timing doesn't reveal which
    # field (if either) was wrong.
    return username_ok and password_ok


def create_session_token(username: str) -> str:
    session_id = secrets.token_urlsafe(32)
    _valid_session_ids.add(session_id)
    serializer = _get_serializer()
    return serializer.dumps({"u": username, "sid": session_id}, salt=SESSION_SALT)


def verify_session_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        serializer = _get_serializer()
        data = serializer.loads(token, salt=SESSION_SALT, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired, AuthConfigError):
        return None

    session_id = data.get("sid")
    if session_id not in _valid_session_ids:
        return None
    return data.get("u")


def invalidate_session_token(token: str | None) -> None:
    if not token:
        return
    try:
        serializer = _get_serializer()
        data = serializer.loads(token, salt=SESSION_SALT, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired, AuthConfigError):
        return
    _valid_session_ids.discard(data.get("sid"))