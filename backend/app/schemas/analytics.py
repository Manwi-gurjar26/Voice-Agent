"""Response shapes for the dashboard's overview endpoint.

Everything here is *derived* — there is no analytics table and no write path.
The numbers are aggregated on read from the rows the product already writes
(conversations, messages, widget sessions, documents), which is the right
tradeoff at this size: a rollup table would need a backfill, a scheduler, and
a reconciliation story to answer questions Postgres answers in one query over
a few thousand rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models.enums import AgentStatus


class DailyPoint(BaseModel):
    """One calendar day (UTC) in the trend series.

    Every day inside the requested window is present, including days with no
    activity — a chart that silently drops empty days draws a misleading line
    between two distant points.
    """

    day: date
    conversations: int
    messages: int
    sessions: int
    input_tokens: int
    output_tokens: int


class PeriodTotals(BaseModel):
    """Aggregates for one window. Returned twice — current and previous — so
    the dashboard can show a real change figure instead of a bare number with
    no sense of direction."""

    conversations: int
    messages: int
    user_messages: int
    assistant_messages: int
    sessions: int
    input_tokens: int
    output_tokens: int
    cited_replies: int
    voice_agents_used: int


class AgentUsage(BaseModel):
    id: uuid.UUID
    name: str
    status: AgentStatus
    voice_enabled: bool
    conversations: int
    messages: int
    input_tokens: int
    output_tokens: int
    last_activity_at: datetime | None


class OriginUsage(BaseModel):
    """Which sites the widget is actually being opened on. Sourced from
    WidgetSession.origin, which was normalised against the agent's allowlist
    at session creation — so these are verified origins, not self-reported
    referrers."""

    origin: str
    sessions: int


class KnowledgeBaseStats(BaseModel):
    documents: int
    ready: int
    pending: int
    processing: int
    failed: int
    characters: int


class QuotaStats(BaseModel):
    plan: str
    used: int
    quota: int
    remaining: int
    percent_used: int
    period_started_at: datetime


class RecentConversation(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    messages: int
    started_at: datetime
    last_message_at: datetime | None


class AnalyticsOverview(BaseModel):
    generated_at: datetime
    range_days: int
    range_start: datetime
    totals: PeriodTotals
    previous_totals: PeriodTotals
    daily: list[DailyPoint]
    agents: list[AgentUsage]
    origins: list[OriginUsage]
    knowledge_base: KnowledgeBaseStats
    quota: QuotaStats
    recent_conversations: list[RecentConversation]
    agents_total: int
    agents_active: int
