"""Dependencies for the public (unauthenticated) widget API.

Unlike the dashboard API (Step 2), there is no user identity here — a request
is authorised by (a) naming an agent's public_key, which is not secret, and
(b) arriving from an origin on that agent's allowlist, or (c) carrying a
widget session token whose underlying agent+origin combination is still
valid. Rate limiting exists because origin checking alone does not stop a
non-browser client from forging the Origin header — see the module docstring
in app/services/rate_limit.py and the README for that caveat.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import DbSession, client_ip
from app.core.config import settings
from app.core.errors import AuthenticationError, NotFoundError, PermissionError_, RateLimitError
from app.core.security import decode_token
from app.models import Agent
from app.models.enums import AgentStatus
from app.models.widget_session import WidgetSession
from app.services import rate_limit

_widget_bearer = HTTPBearer(auto_error=False, description="Widget session token")


async def resolve_public_agent(public_key: str, request: Request, db: DbSession) -> Agent:
    """Look up an active agent and check the request's Origin against its
    allowlist. Used by every route that has {public_key} in its path.

    On success, stashes the normalized origin on request.state — that's how
    PublicWidgetCorsMiddleware (app/core/middleware.py) decides whether to add
    Access-Control-Allow-Origin to the response, without a second DB lookup.
    """
    agent = await db.scalar(
        select(Agent).where(Agent.public_key == public_key, Agent.status == AgentStatus.ACTIVE)
    )
    if agent is None:
        raise NotFoundError("Agent not found or not active.")

    origin = request.headers.get("Origin")
    if not agent.is_origin_allowed(origin):
        # public_key is not a secret (it ships in page source), so unlike the
        # tenant-isolation checks in Step 2 there is no reason to hide behind
        # a 404 here — a clear message lets customers fix a misconfigured
        # allowlist instead of guessing.
        raise PermissionError_(
            "This origin is not permitted to use this widget.", code="origin_not_allowed"
        )

    request.state.cors_origin = Agent.normalize_origin(origin)
    return agent


PublicAgent = Annotated[Agent, Depends(resolve_public_agent)]


async def _enforce_rate_limit_for_agent(agent: Agent, ip: str | None) -> None:
    result = await rate_limit.check(
        f"public:{agent.id}:{ip or 'unknown'}",
        limit=agent.rate_limit_per_minute,
        window_seconds=settings.public_rate_limit_window_seconds,
    )
    if not result.allowed:
        raise RateLimitError(
            "Too many requests to this widget. Please slow down.",
            details={"retry_after": result.retry_after},
            headers={"Retry-After": str(result.retry_after)},
        )


async def enforce_public_rate_limit(
    agent: PublicAgent, ip: Annotated[str | None, Depends(client_ip)]
) -> None:
    """One shared per-(agent, IP) budget across every {public_key}-in-path
    route (config reads, session creation) — simple for now; split into
    per-action tiers if usage patterns call for it later."""
    await _enforce_rate_limit_for_agent(agent, ip)


async def get_widget_session(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_widget_bearer)] = None,
) -> WidgetSession:
    """Resolve and re-validate a widget session token.

    Re-checks the session, its agent, and the origin on every call — the same
    always-re-read-from-the-database policy used for user access tokens in
    Step 2, so revoking a session or disabling an agent takes effect
    immediately instead of waiting for the token to expire.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("Missing widget session token.")

    try:
        payload = decode_token(credentials.credentials, expected_type="widget_session")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Widget session has expired.", code="session_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid widget session token.") from exc

    try:
        session_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid widget session token.") from exc

    session = await db.scalar(
        select(WidgetSession)
        .where(WidgetSession.id == session_id)
        .options(joinedload(WidgetSession.agent).joinedload(Agent.tenant))
    )
    now = datetime.now(timezone.utc)
    if (
        session is None
        or not session.is_usable(now)
        or session.agent.status != AgentStatus.ACTIVE
        or not session.agent.tenant.is_active
    ):
        raise AuthenticationError("Widget session is no longer valid.")

    origin = request.headers.get("Origin")
    if not session.agent.is_origin_allowed(origin):
        raise PermissionError_(
            "This origin is not permitted to use this widget.", code="origin_not_allowed"
        )

    # Same stash as resolve_public_agent, for the same reason: this route has
    # no {public_key} in its path, so the CORS middleware cannot look the
    # agent up itself — it relies entirely on this dependency having run.
    request.state.cors_origin = Agent.normalize_origin(origin)
    return session


WidgetSessionDep = Annotated[WidgetSession, Depends(get_widget_session)]


async def enforce_session_rate_limit(
    session: WidgetSessionDep, ip: Annotated[str | None, Depends(client_ip)]
) -> None:
    """Same per-(agent, IP) bucket as enforce_public_rate_limit, keyed
    identically, for routes authenticated by a widget session token instead
    of {public_key} in the path (conversation creation, sending a message).
    One shared cost-exposure budget per agent per visitor, regardless of
    which route they hit — this is deliberately the most heavily-protected
    bucket, since a chat message is what actually triggers a Gemini call.
    """
    await _enforce_rate_limit_for_agent(session.agent, ip)
