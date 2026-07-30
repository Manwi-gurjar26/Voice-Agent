"""Shared request dependencies: authentication and tenant scoping."""

from __future__ import annotations

import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, PermissionError_
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User
from app.models.enums import UserRole

# auto_error=False so a missing header produces our JSON envelope rather than
# Starlette's bare 403.
_bearer = HTTPBearer(auto_error=False, description="Access token from /auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing bearer token.")

    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token has expired.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid access token.") from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid access token.") from exc

    # The token is signed, but authorisation state can change during its
    # lifetime — a deactivated user must lose access immediately, not in 30
    # minutes. So the user is always re-read.
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active or not user.tenant.is_active:
        raise AuthenticationError("Account is no longer active.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_tenant_id(user: CurrentUser) -> uuid.UUID:
    """The only sanctioned source of tenant_id for a request.

    Endpoints take this instead of reading a tenant id from the path or body,
    so there is no code path in which a client can name someone else's tenant.
    """
    return user.tenant_id


TenantId = Annotated[uuid.UUID, Depends(get_tenant_id)]


def require_roles(*roles: UserRole):
    """Restrict an endpoint to the given roles."""
    allowed = set(roles)

    async def _dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionError_(
                f"This action requires one of: {', '.join(sorted(allowed))}."
            )
        return user

    return _dependency


RequireAdmin = Annotated[User, Depends(require_roles(UserRole.OWNER, UserRole.ADMIN))]

# Billing is more sensitive than agent configuration (it's the one thing
# that moves money) — owner-only, not owner-or-admin.
RequireOwner = Annotated[User, Depends(require_roles(UserRole.OWNER))]


def client_ip(request: Request) -> str | None:
    """Best-effort client IP.

    X-Forwarded-For is trusted only because this service is expected to sit
    behind a proxy that overwrites it. Directly exposed, the header is
    attacker-controlled — revisit when deployment is finalised in Step 10.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None
