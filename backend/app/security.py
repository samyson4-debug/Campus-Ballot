"""
Campus Ballot — Security Module
Handles password hashing (PBKDF2-HMAC-SHA256), password policy validation,
and JWT token creation / verification.

SECURITY-CRITICAL: This module uses only stdlib for crypto operations.
- PBKDF2 with a configurable iteration count (default 600,000).
- 16-byte random salt per password via `secrets.token_bytes`.
- Constant-time comparison via `secrets.compare_digest`.
- Malformed stored hashes fail safely (return False, never raise).
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

# ---------------------------------------------------------------------------
# Password hashing constants
# ---------------------------------------------------------------------------
PBKDF2_ITERATIONS: int = settings.PBKDF2_ITERATIONS
HASH_ALGORITHM: str = "sha256"
SALT_LENGTH: int = 16  # bytes
HASH_FORMAT_SEP: str = ":"  # stored as  salt_hex:hash_hex


def hash_password(plain: str) -> str:
    """
    Hash a plaintext password with PBKDF2-HMAC-SHA256.
    Returns ``salt_hex:hash_hex``.
    """
    salt = secrets.token_bytes(SALT_LENGTH)
    dk = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM, plain.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}{HASH_FORMAT_SEP}{dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """
    Verify *plain* against a stored ``salt_hex:hash_hex`` string.

    SECURITY: uses `secrets.compare_digest` for constant-time comparison.
    Any malformed *stored* value (missing separator, non-hex, etc.) causes
    a safe ``False`` return — never an unhandled exception.
    """
    try:
        parts = stored.split(HASH_FORMAT_SEP)
        if len(parts) != 2:
            return False
        salt_hex, hash_hex = parts
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        # Non-hex characters, None input, etc.
        return False

    dk = hashlib.pbkdf2_hmac(
        HASH_ALGORITHM, plain.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    # SECURITY: constant-time comparison prevents timing attacks.
    return secrets.compare_digest(dk, expected)


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
# Minimum 8 chars, at least one uppercase, one lowercase, one digit, one special.
_PASSWORD_RULES = [
    (lambda p: len(p) >= 8, "Password must be at least 8 characters long."),
    (lambda p: re.search(r"[A-Z]", p) is not None, "Password must contain at least one uppercase letter."),
    (lambda p: re.search(r"[a-z]", p) is not None, "Password must contain at least one lowercase letter."),
    (lambda p: re.search(r"\d", p) is not None, "Password must contain at least one digit."),
    (
        lambda p: re.search(r"[!@#$%^&*()_+\-=\[\]{}|;':\",./<>?\\`~]", p) is not None,
        "Password must contain at least one special character.",
    ),
]


def validate_password(password: str) -> list[str]:
    """Return a list of policy-violation messages (empty → password is valid)."""
    return [msg for check, msg in _PASSWORD_RULES if not check(password)]


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
JWT_ALGORITHM = "HS256"


def create_access_token(subject: str, role: str, extra: dict | None = None) -> str:
    """
    Create a signed JWT with ``sub``, ``role``, ``exp`` claims.
    ``subject`` is the user's primary key id (str).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=settings.SESSION_HOURS),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """
    Decode and verify a JWT.  Returns the payload dict or ``None`` on any
    error (expired, tampered, malformed).
    """
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
