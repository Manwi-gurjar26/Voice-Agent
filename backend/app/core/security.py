"""Password hashing, token signing, and public-key generation.

Used by the auth endpoints in Step 2, but it lives in core because the models
and the widget API both depend on the key formats defined here.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh", "widget_session"]

_PUBLIC_KEY_PREFIX = "agt_pub"
_SECRET_KEY_PREFIX = "agt_sk"


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def _prepare_password(password: str) -> bytes:
    """Normalise a password to a fixed-length input for bcrypt.

    bcrypt silently truncates anything past 72 bytes, which would make
    "longpassword...A" and "longpassword...B" equivalent. SHA-256 + base64
    yields a constant 44-byte digest, so the full password always contributes.
    """
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare_password(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare_password(password), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # Malformed hash in the DB — treat as a failed login, never a 500.
        return False


# --------------------------------------------------------------------------
# JWTs
# --------------------------------------------------------------------------
def create_token(
    subject: str | uuid.UUID,
    token_type: TokenType,
    *,
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    if expires_delta is not None:
        lifetime = expires_delta
    elif token_type == "access":
        lifetime = timedelta(minutes=settings.access_token_expire_minutes)
    elif token_type == "refresh":
        lifetime = timedelta(days=settings.refresh_token_expire_days)
    else:
        lifetime = timedelta(minutes=settings.widget_session_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "nbf": now,
        "exp": now + lifetime,
        "jti": secrets.token_urlsafe(16),
    }
    if extra_claims:
        # Never let callers overwrite the registered claims above.
        payload.update({k: v for k, v in extra_claims.items() if k not in payload})
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate a token. Raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )
    if expected_type is not None and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload


# --------------------------------------------------------------------------
# Agent keys
# --------------------------------------------------------------------------
def generate_agent_public_key() -> str:
    """Public identifier embedded in the customer's <script> tag.

    Not a secret: it ships in page source. Authorisation for the public API is
    the agent's origin allowlist plus rate limiting, never this key alone.
    """
    return f"{_PUBLIC_KEY_PREFIX}_{secrets.token_urlsafe(24)}"


def generate_refresh_token() -> tuple[str, str]:
    """Opaque refresh token. Returns (plaintext, hash) — store only the hash.

    Deliberately not a JWT: refresh tokens must be revocable the instant they
    are rotated, which needs a server-side record anyway. The hash is
    deterministic so the record can be found with an indexed lookup.
    """
    plaintext = secrets.token_urlsafe(48)
    return plaintext, hash_secret_key(plaintext)


def generate_agent_secret_key() -> tuple[str, str]:
    """Server-to-server key. Returns (plaintext, hash) — store only the hash."""
    plaintext = f"{_SECRET_KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return plaintext, hash_secret_key(plaintext)


def generate_password_reset_token() -> tuple[str, str]:
    """Opaque password-reset token. Returns (plaintext, hash) — store only
    the hash, same reasoning as generate_refresh_token: a database leak
    alone must not yield a usable token."""
    plaintext = secrets.token_urlsafe(48)
    return plaintext, hash_secret_key(plaintext)


def hash_secret_key(plaintext: str) -> str:
    """Fast keyed hash — API keys are high-entropy, so bcrypt's cost is wasted
    here and would add latency to every request."""
    return hmac.new(
        settings.secret_key.encode("utf-8"), plaintext.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def verify_secret_key(plaintext: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret_key(plaintext), stored_hash)
