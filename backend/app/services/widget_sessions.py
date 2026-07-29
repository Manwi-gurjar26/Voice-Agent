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


async def create_widget_session(
    db: AsyncSession,
    agent: Agent,
    *,
    origin: str,
    user_agent: str | None,
    ip_address: str | None,
) -> WidgetSessionResponse:
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

    token = create_token(
        session.id,
        "widget_session",
        expires_delta=timedelta(minutes=settings.widget_session_expire_minutes),
        extra_claims={"agent_id": str(agent.id), "tenant_id": str(agent.tenant_id)},
    )
    return WidgetSessionResponse(
        session_token=token, expires_in=settings.widget_session_expire_minutes * 60
    )
