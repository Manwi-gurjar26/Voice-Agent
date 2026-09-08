"""Widget session creation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_token
from app.models import Agent
from app.models.widget_session import WidgetSession
from app.schemas.public import WidgetSessionResponse


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def new_widget_session(
    db: AsyncSession,
    agent: Agent,
    *,
    origin: str,
    user_agent: str | None,
    ip_address: str | None,
) -> WidgetSession:
    """Insert and flush the session row, returning the row itself.

    Split out from create_widget_session because the dashboard preview
    (app/api/v1/preview.py) needs the session *object* to hang a conversation
    off, and has no use for a token — it is already authenticated as the
    agent's owner. Re-querying for the row it had just written was the
    alternative, and would race with any concurrent session for the same
    agent.
    """
    session = WidgetSession(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        origin=origin,
        user_agent=(user_agent or "")[:255] or None,
        ip_address=(ip_address or "")[:45] or None,
        expires_at=_now() + timedelta(minutes=settings.widget_session_expire_minutes),
    )
    db.add(session)
    await db.flush()
    return session


async def create_widget_session(
    db: AsyncSession,
    agent: Agent,
    *,
    origin: str,
    user_agent: str | None,
    ip_address: str | None,
) -> WidgetSessionResponse:
    session = await new_widget_session(
        db, agent, origin=origin, user_agent=user_agent, ip_address=ip_address
    )

    token = create_token(
        session.id,
        "widget_session",
        expires_delta=timedelta(minutes=settings.widget_session_expire_minutes),
        extra_claims={"agent_id": str(agent.id), "tenant_id": str(agent.tenant_id)},
    )
    return WidgetSessionResponse(
        session_token=token, expires_in=settings.widget_session_expire_minutes * 60
    )
