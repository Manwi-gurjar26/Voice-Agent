"""Read-only aggregation for the dashboard overview.

Every query here filters on tenant_id in its WHERE clause (never as an
assertion afterwards), same rule as app/services/agents.py — a tenant can
only ever aggregate its own rows.

Conversations, not messages, carry tenant_id, so message-level aggregates
join back through Conversation rather than trusting a denormalised column
that does not exist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models import Agent, Conversation, Document, Message, Tenant, WidgetSession
from app.schemas.analytics import (
    AgentUsage,
    AnalyticsOverview,
    DailyPoint,
    KnowledgeBaseStats,
    OriginUsage,
    PeriodTotals,
    QuotaStats,
    RecentConversation,
)

# How many rows the "long tail" sections return. These are dashboard cards,
# not exports — an unbounded list would be both slow and unreadable.
MAX_AGENTS = 12
MAX_ORIGINS = 8
MAX_RECENT_CONVERSATIONS = 10


def _window(days: int, *, now: datetime) -> tuple[datetime, datetime]:
    """The current window and the equally-long one immediately before it.

    Anchored to midnight UTC rather than "now minus N days" so the series
    lines up with the calendar-day buckets the chart draws, and so two
    requests a minute apart return the same buckets instead of a shifting
    window.
    """
    end = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    start = end - timedelta(days=days)
    return start, end


async def _totals(
    db: AsyncSession, tenant_id: uuid.UUID, start: datetime, end: datetime
) -> PeriodTotals:
    """One window's aggregates, as three grouped queries rather than one wide
    join — joining sessions to conversations to messages in a single statement
    multiplies rows and silently inflates every count."""
    conversations = await db.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(
            Conversation.tenant_id == tenant_id,
            Conversation.created_at >= start,
            Conversation.created_at < end,
        )
    )

    sessions = await db.scalar(
        select(func.count())
        .select_from(WidgetSession)
        .where(
            WidgetSession.tenant_id == tenant_id,
            WidgetSession.created_at >= start,
            WidgetSession.created_at < end,
        )
    )

    # coalesce, not sum-or-None: input_tokens/output_tokens are NULL on every
    # user row and on assistant rows written before usage metadata existed.
    message_row = (
        await db.execute(
            select(
                func.count(Message.id),
                func.count(case((Message.role == "user", 1))),
                func.count(case((Message.role == "assistant", 1))),
                func.coalesce(func.sum(Message.input_tokens), 0),
                func.coalesce(func.sum(Message.output_tokens), 0),
                # Deliberately not jsonb_array_length: postgresql.JSONB maps
                # Python None to the jsonb scalar 'null' (not SQL NULL), and
                # jsonb_array_length errors outright on a scalar. Requiring
                # the value to be a non-empty array is equivalent, and total
                # over every shape the column actually holds — SQL NULL from
                # older rows, 'null', [], and a real citation list.
                func.count(
                    case(
                        (
                            (func.jsonb_typeof(Message.citations) == "array")
                            & (Message.citations != cast([], JSONB)),
                            1,
                        )
                    )
                ),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.tenant_id == tenant_id,
                Message.created_at >= start,
                Message.created_at < end,
            )
        )
    ).one()

    # "Voice agents used" counts agents that both have voice on and saw
    # traffic in the window — a voice-enabled agent nobody spoke to is not
    # evidence that voice is being used.
    voice_agents_used = await db.scalar(
        select(func.count(func.distinct(Conversation.agent_id)))
        .select_from(Conversation)
        .join(Agent, Agent.id == Conversation.agent_id)
        .where(
            Conversation.tenant_id == tenant_id,
            Agent.voice_enabled.is_(True),
            Conversation.created_at >= start,
            Conversation.created_at < end,
        )
    )

    return PeriodTotals(
        conversations=int(conversations or 0),
        messages=int(message_row[0] or 0),
        user_messages=int(message_row[1] or 0),
        assistant_messages=int(message_row[2] or 0),
        sessions=int(sessions or 0),
        input_tokens=int(message_row[3] or 0),
        output_tokens=int(message_row[4] or 0),
        cited_replies=int(message_row[5] or 0),
        voice_agents_used=int(voice_agents_used or 0),
    )


def _utc_day(column):
    """Bucket a timestamptz by UTC calendar day.

    `date_trunc('day', <timestamptz>)` truncates in the *session* TimeZone,
    not UTC, and hands back a timestamptz. On a server set to Asia/Calcutta
    that turns 2026-09-05T12:24Z into 2026-09-04T18:30Z — IST midnight on the
    5th, expressed in UTC — and reading `.date()` off it yields the 4th. Every
    point in the series then lands on the wrong day, and for any zone east of
    UTC the most recent bucket can fall outside the spine entirely, so today's
    activity silently disappears from the chart.

    `AT TIME ZONE 'UTC'` first converts to a naive timestamp in UTC, so the
    truncation and the Python-side `.date()` agree with the UTC window
    `_window()` builds. Not a default worth relying on: the session timezone
    is deployment configuration, and this must not depend on it.
    """
    return func.date_trunc("day", func.timezone("UTC", column))


async def _daily(
    db: AsyncSession, tenant_id: uuid.UUID, start: datetime, end: datetime, days: int
) -> list[DailyPoint]:
    """The trend series, with every empty day filled in.

    The date spine is built in Python instead of with generate_series so the
    three separate grouped queries (which each know only about the days they
    have rows for) can be merged onto one complete axis.
    """
    day = _utc_day(Conversation.created_at)
    conv_rows = (
        await db.execute(
            select(day, func.count())
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.created_at >= start,
                Conversation.created_at < end,
            )
            .group_by(day)
        )
    ).all()

    msg_day = _utc_day(Message.created_at)
    msg_rows = (
        await db.execute(
            select(
                msg_day,
                func.count(),
                func.coalesce(func.sum(Message.input_tokens), 0),
                func.coalesce(func.sum(Message.output_tokens), 0),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.tenant_id == tenant_id,
                Message.created_at >= start,
                Message.created_at < end,
            )
            .group_by(msg_day)
        )
    ).all()

    sess_day = _utc_day(WidgetSession.created_at)
    sess_rows = (
        await db.execute(
            select(sess_day, func.count())
            .where(
                WidgetSession.tenant_id == tenant_id,
                WidgetSession.created_at >= start,
                WidgetSession.created_at < end,
            )
            .group_by(sess_day)
        )
    ).all()

    conversations: dict[date, int] = {r[0].date(): int(r[1]) for r in conv_rows}
    sessions: dict[date, int] = {r[0].date(): int(r[1]) for r in sess_rows}
    messages: dict[date, tuple[int, int, int]] = {
        r[0].date(): (int(r[1]), int(r[2] or 0), int(r[3] or 0)) for r in msg_rows
    }

    spine = [(start + timedelta(days=offset)).date() for offset in range(days)]
    points = []
    for d in spine:
        count, tokens_in, tokens_out = messages.get(d, (0, 0, 0))
        points.append(
            DailyPoint(
                day=d,
                conversations=conversations.get(d, 0),
                messages=count,
                sessions=sessions.get(d, 0),
                input_tokens=tokens_in,
                output_tokens=tokens_out,
            )
        )
    return points


async def _agents(
    db: AsyncSession, tenant_id: uuid.UUID, start: datetime, end: datetime
) -> tuple[list[AgentUsage], int, int]:
    """Per-agent usage, plus the tenant's total/active agent counts.

    LEFT OUTER JOIN, so an agent with no traffic still appears with zeros
    rather than vanishing from the table — "which of my agents is doing
    nothing" is exactly what this view is for.
    """
    rows = (
        await db.execute(
            select(
                Agent.id,
                Agent.name,
                Agent.status,
                Agent.voice_enabled,
                func.count(func.distinct(Conversation.id)),
                func.max(Conversation.last_message_at),
            )
            .select_from(Agent)
            .outerjoin(
                Conversation,
                (Conversation.agent_id == Agent.id)
                & (Conversation.created_at >= start)
                & (Conversation.created_at < end),
            )
            .where(Agent.tenant_id == tenant_id)
            .group_by(Agent.id, Agent.name, Agent.status, Agent.voice_enabled)
        )
    ).all()

    # Message counts come from a second query keyed by agent, for the same
    # row-multiplication reason as _totals.
    message_rows = (
        await db.execute(
            select(
                Conversation.agent_id,
                func.count(Message.id),
                func.coalesce(func.sum(Message.input_tokens), 0),
                func.coalesce(func.sum(Message.output_tokens), 0),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.tenant_id == tenant_id,
                Message.created_at >= start,
                Message.created_at < end,
            )
            .group_by(Conversation.agent_id)
        )
    ).all()
    by_agent = {r[0]: (int(r[1]), int(r[2] or 0), int(r[3] or 0)) for r in message_rows}

    usage = []
    for agent_id, name, status, voice_enabled, conversations, last_activity in rows:
        messages, tokens_in, tokens_out = by_agent.get(agent_id, (0, 0, 0))
        usage.append(
            AgentUsage(
                id=agent_id,
                name=name,
                status=status,
                voice_enabled=voice_enabled,
                conversations=int(conversations or 0),
                messages=messages,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                last_activity_at=last_activity,
            )
        )

    total = len(usage)
    active = sum(1 for a in usage if a.status == "active")
    # Busiest first; name breaks ties so the order is stable across requests
    # for the (common, early) case where every agent has zero traffic.
    usage.sort(key=lambda a: (-a.messages, -a.conversations, a.name.lower()))
    return usage[:MAX_AGENTS], total, active


async def _origins(
    db: AsyncSession, tenant_id: uuid.UUID, start: datetime, end: datetime
) -> list[OriginUsage]:
    rows = (
        await db.execute(
            select(WidgetSession.origin, func.count())
            .where(
                WidgetSession.tenant_id == tenant_id,
                WidgetSession.created_at >= start,
                WidgetSession.created_at < end,
            )
            .group_by(WidgetSession.origin)
            .order_by(func.count().desc(), WidgetSession.origin)
            .limit(MAX_ORIGINS)
        )
    ).all()
    return [OriginUsage(origin=r[0], sessions=int(r[1])) for r in rows]


async def _knowledge_base(db: AsyncSession, tenant_id: uuid.UUID) -> KnowledgeBaseStats:
    """Not windowed: a knowledge base is current state, not activity. A
    document that failed to ingest last month is still broken today."""
    row = (
        await db.execute(
            select(
                func.count(),
                func.count(case((Document.status == "ready", 1))),
                func.count(case((Document.status == "pending", 1))),
                func.count(case((Document.status == "processing", 1))),
                func.count(case((Document.status == "failed", 1))),
                func.coalesce(func.sum(Document.char_count), 0),
            ).where(Document.tenant_id == tenant_id)
        )
    ).one()
    return KnowledgeBaseStats(
        documents=int(row[0] or 0),
        ready=int(row[1] or 0),
        pending=int(row[2] or 0),
        processing=int(row[3] or 0),
        failed=int(row[4] or 0),
        characters=int(row[5] or 0),
    )


async def _recent(db: AsyncSession, tenant_id: uuid.UUID) -> list[RecentConversation]:
    rows = (
        await db.execute(
            select(
                Conversation.id,
                Agent.id,
                Agent.name,
                func.count(Message.id),
                Conversation.created_at,
                Conversation.last_message_at,
            )
            .select_from(Conversation)
            .join(Agent, Agent.id == Conversation.agent_id)
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(Conversation.tenant_id == tenant_id)
            .group_by(
                Conversation.id,
                Agent.id,
                Agent.name,
                Conversation.created_at,
                Conversation.last_message_at,
            )
            # NULLS LAST: a conversation that was opened but never sent a
            # message has no last_message_at, and must not outrank a real one.
            .order_by(
                func.coalesce(Conversation.last_message_at, Conversation.created_at).desc(),
                Conversation.id,
            )
            .limit(MAX_RECENT_CONVERSATIONS)
        )
    ).all()
    return [
        RecentConversation(
            id=r[0],
            agent_id=r[1],
            agent_name=r[2],
            messages=int(r[3] or 0),
            started_at=r[4],
            last_message_at=r[5],
        )
        for r in rows
    ]


async def overview(
    db: AsyncSession, tenant_id: uuid.UUID, *, days: int = 30
) -> AnalyticsOverview:
    now = datetime.now(UTC)
    start, end = _window(days, now=now)
    prev_start = start - timedelta(days=days)

    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:  # pragma: no cover — a live session's tenant always exists
        raise NotFoundError("Workspace not found.")

    totals = await _totals(db, tenant_id, start, end)
    previous_totals = await _totals(db, tenant_id, prev_start, start)
    daily = await _daily(db, tenant_id, start, end, days)
    agents, agents_total, agents_active = await _agents(db, tenant_id, start, end)
    origins = await _origins(db, tenant_id, start, end)
    knowledge_base = await _knowledge_base(db, tenant_id)
    recent_conversations = await _recent(db, tenant_id)

    quota = max(tenant.monthly_message_quota, 0)
    used = max(tenant.messages_used_in_period, 0)
    return AnalyticsOverview(
        generated_at=now,
        range_days=days,
        range_start=start,
        totals=totals,
        previous_totals=previous_totals,
        daily=daily,
        agents=agents,
        origins=origins,
        knowledge_base=knowledge_base,
        quota=QuotaStats(
            plan=str(tenant.plan),
            used=used,
            quota=quota,
            remaining=max(quota - used, 0),
            # A zero quota is 100% consumed, not a division by zero.
            percent_used=min(100, round(used / quota * 100)) if quota else 100,
            period_started_at=tenant.period_started_at,
        ),
        recent_conversations=recent_conversations,
        agents_total=agents_total,
        agents_active=agents_active,
    )
