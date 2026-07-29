"""Signup, login, and refresh-token rotation."""

from __future__ import annotations

import logging
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import (
    create_token,
    generate_refresh_token,
    hash_password,
    hash_secret_key,
    verify_password,
)
from app.models import RefreshToken, Tenant, User
from app.models.enums import UserRole
from app.schemas.auth import SignupRequest, TokenPair

logger = logging.getLogger(__name__)

# Deliberately identical for "no such user", "wrong password", and "inactive".
# Distinct messages would let an attacker enumerate registered addresses.
_INVALID_CREDENTIALS = "Incorrect email or password."


def slugify(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value).strip("-").lower()
    return slug[:60] or "tenant"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _unique_slug(db: AsyncSession, base: str) -> str:
    """Find a free slug.

    A random suffix rather than an incrementing counter: `-2`, `-3` would leak
    how many tenants share a company name, and would need a retry loop under
    concurrent signups.
    """
    if not await db.scalar(select(Tenant.id).where(Tenant.slug == base).limit(1)):
        return base
    for _ in range(5):
        candidate = f"{base[:52]}-{secrets.token_hex(3)}"
        if not await db.scalar(select(Tenant.id).where(Tenant.slug == candidate).limit(1)):
            return candidate
    raise ConflictError("Could not allocate a workspace identifier. Please try again.")


async def signup(db: AsyncSession, payload: SignupRequest) -> tuple[User, Tenant]:
    """Create a tenant and its first (owner) user."""
    existing = await db.scalar(select(User.id).where(User.email == payload.email).limit(1))
    if existing:
        raise ConflictError("An account with this email already exists.")

    tenant = Tenant(
        name=payload.company_name.strip(),
        slug=await _unique_slug(db, slugify(payload.company_name)),
    )
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.OWNER,  # the first user of a tenant always owns it
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Two concurrent signups for the same address; the unique index wins.
        await db.rollback()
        raise ConflictError("An account with this email already exists.") from exc

    return user, tenant


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    """Verify credentials, applying lockout. Raises AuthenticationError."""
    now = _now()
    user = await db.scalar(select(User).where(User.email == email))

    if user is None:
        # Spend comparable time on a dummy hash so response timing does not
        # reveal whether the address exists.
        verify_password(password, hash_password(secrets.token_urlsafe(16)))
        raise AuthenticationError(_INVALID_CREDENTIALS)

    if user.is_locked(now):
        raise AuthenticationError(
            "Too many failed attempts. Try again later.", code="account_locked"
        )

    if not verify_password(password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.max_failed_logins:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            logger.warning("account locked after repeated failures", extra={"user_id": str(user.id)})
        # Commit before raising. get_db rolls back when a request raises, so a
        # plain flush() here would be discarded along with the 401 — the
        # counter would reset on every attempt and lockout could never trigger.
        await db.commit()
        raise AuthenticationError(_INVALID_CREDENTIALS)

    if not user.is_active or not user.tenant.is_active:
        raise AuthenticationError(_INVALID_CREDENTIALS)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    await db.flush()
    return user


async def issue_token_pair(
    db: AsyncSession,
    user: User,
    *,
    family_id: uuid.UUID | None = None,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    plaintext, token_hash = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
            user_agent=(user_agent or "")[:255] or None,
            ip_address=(ip_address or "")[:45] or None,
        )
    )
    await db.flush()

    return TokenPair(
        access_token=create_token(user.id, "access", extra_claims={"tid": str(user.tenant_id)}),
        refresh_token=plaintext,
        expires_in=settings.access_token_expire_minutes * 60,
    )


async def rotate_refresh_token(
    db: AsyncSession,
    raw_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    """Exchange a refresh token for a new pair, revoking the old one.

    Presenting an already-revoked token means it was captured and replayed, so
    the entire family is revoked — the legitimate holder is logged out too,
    which is the correct outcome once a token is known to have leaked.
    """
    now = _now()
    record = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_secret_key(raw_token))
    )
    if record is None:
        raise AuthenticationError("Invalid refresh token.")

    if record.revoked_at is not None:
        logger.warning(
            "refresh token reuse detected; revoking family",
            extra={"user_id": str(record.user_id), "family_id": str(record.family_id)},
        )
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == record.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        # Commit before raising, for the same reason as the login counter: the
        # 401 would otherwise roll back the revocation and leave the stolen
        # token chain live — the exact opposite of the intended response.
        await db.commit()
        raise AuthenticationError("Invalid refresh token.")

    if record.expires_at <= now:
        raise AuthenticationError("Refresh token has expired.")

    user = await db.scalar(select(User).where(User.id == record.user_id))
    if user is None or not user.is_active or not user.tenant.is_active:
        raise AuthenticationError("Invalid refresh token.")

    record.revoked_at = now
    return await issue_token_pair(
        db, user, family_id=record.family_id, user_agent=user_agent, ip_address=ip_address
    )


async def revoke_refresh_token(db: AsyncSession, raw_token: str) -> None:
    """Log out one session. Silent when the token is unknown — logout must not
    become an oracle for which tokens exist."""
    record = await db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_secret_key(raw_token))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = _now()
        await db.flush()


async def revoke_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Log out every session — used on password change and by 'sign out everywhere'."""
    result = await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.flush()
    return result.rowcount or 0
