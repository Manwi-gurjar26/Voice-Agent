"""Tenant message-quota enforcement."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceededError
from app.models import Tenant

# A rolling window, not a calendar month — see Tenant.period_started_at.
QUOTA_PERIOD = timedelta(days=30)


async def check_and_consume_quota(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Row-locked check-and-increment against the tenant's message quota.

    FOR UPDATE serializes concurrent messages for the same tenant so two
    requests racing at the limit can't both slip through underneath it. The
    lock is held only for this one increment (released at the next commit,
    which the caller issues immediately after) — not for the whole Claude
    call, so a busy tenant's other agents/visitors aren't serialized behind
    this one message.

    Raises QuotaExceededError without consuming anything if the tenant is
    already at its limit.
    """
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    now = datetime.now(timezone.utc)

    if now - tenant.period_started_at >= QUOTA_PERIOD:
        tenant.period_started_at = now
        tenant.messages_used_in_period = 0

    if tenant.messages_used_in_period >= tenant.monthly_message_quota:
        raise QuotaExceededError()

    tenant.messages_used_in_period += 1
