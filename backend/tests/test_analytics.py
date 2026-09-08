from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from app.core.config import settings
from app.models import Agent, Conversation, Document, Message, WidgetSession
from tests.test_agents import make_agent
from tests.test_auth import bearer, register

PREFIX = settings.api_v1_prefix
ORIGIN = "https://shop.acme.example.com"


def _midnight_utc(days_ago: int) -> datetime:
    """A timestamp inside the bucket `days_ago` days back.

    Midday, not midnight: the service buckets on date_trunc('day'), and a
    timestamp exactly on a boundary is the one value where an off-by-one in
    the window maths would go unnoticed.
    """
    today = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), tzinfo=UTC)
    return today - timedelta(days=days_ago) + timedelta(hours=12)


async def _agent_row(db_session, agent_id: str) -> Agent:
    agent = await db_session.scalar(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    assert agent is not None
    return agent


async def seed_conversation(
    db_session,
    agent: Agent,
    *,
    days_ago: int = 0,
    user_messages: int = 1,
    assistant_messages: int = 1,
    input_tokens: int = 100,
    output_tokens: int = 40,
    citations: list[dict] | None = None,
    origin: str = ORIGIN,
) -> Conversation:
    """Insert one widget session, conversation, and its messages at a chosen
    point in the past.

    Written directly rather than driven through the public chat API because
    these tests are about the *aggregation*, and the public API can only ever
    create rows dated now — which would make every windowing assertion below
    untestable.
    """
    at = _midnight_utc(days_ago)

    session = WidgetSession(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        origin=origin,
        user_agent="pytest",
        ip_address="127.0.0.1",
        expires_at=at + timedelta(hours=12),
        created_at=at,
        updated_at=at,
    )
    db_session.add(session)
    await db_session.flush()

    conversation = Conversation(
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        widget_session_id=session.id,
        last_message_at=at,
        created_at=at,
        updated_at=at,
    )
    db_session.add(conversation)
    await db_session.flush()

    for i in range(user_messages):
        db_session.add(
            Message(
                conversation_id=conversation.id,
                role="user",
                content=f"question {i}",
                created_at=at,
                updated_at=at,
            )
        )
    for i in range(assistant_messages):
        db_session.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=f"answer {i}",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                citations=citations,
                created_at=at,
                updated_at=at,
            )
        )
    await db_session.flush()
    return conversation


async def fetch_overview(client, tokens, **params) -> dict:
    response = await client.get(
        f"{PREFIX}/analytics/overview", params=params, headers=bearer(tokens)
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------
async def test_overview_requires_authentication(client):
    response = await client.get(f"{PREFIX}/analytics/overview")
    assert response.status_code == 401


async def test_overview_never_counts_another_tenants_rows(client, db_session):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")

    agent_b = await _agent_row(
        db_session, (await make_agent(client, tokens_b, name="Globex Bot"))["id"]
    )
    await seed_conversation(db_session, agent_b, user_messages=3, assistant_messages=3)

    overview = await fetch_overview(client, tokens_a)
    assert overview["totals"]["conversations"] == 0
    assert overview["totals"]["messages"] == 0
    assert overview["agents"] == []
    assert overview["origins"] == []
    assert overview["recent_conversations"] == []


# --------------------------------------------------------------------------
# Totals
# --------------------------------------------------------------------------
async def test_totals_split_messages_by_role_and_sum_tokens(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])

    await seed_conversation(
        db_session, agent, user_messages=2, assistant_messages=2, input_tokens=120, output_tokens=30
    )
    await seed_conversation(
        db_session,
        agent,
        days_ago=3,
        user_messages=1,
        assistant_messages=1,
        input_tokens=80,
        output_tokens=20,
    )

    totals = (await fetch_overview(client, tokens))["totals"]
    assert totals["conversations"] == 2
    assert totals["sessions"] == 2
    assert totals["messages"] == 6
    assert totals["user_messages"] == 3
    assert totals["assistant_messages"] == 3
    # Only assistant rows carry usage: 2×120 + 1×80.
    assert totals["input_tokens"] == 320
    assert totals["output_tokens"] == 80


async def test_cited_replies_counts_only_answers_that_used_the_knowledge_base(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])

    await seed_conversation(
        db_session, agent, citations=[{"document_id": str(uuid.uuid4()), "title": "Pricing"}]
    )
    await seed_conversation(db_session, agent, citations=[])
    await seed_conversation(db_session, agent, citations=None)

    totals = (await fetch_overview(client, tokens))["totals"]
    assert totals["conversations"] == 3
    assert totals["cited_replies"] == 1


async def test_voice_agents_used_ignores_voice_agents_with_no_traffic(client, db_session):
    tokens = await register(client)
    voice = await _agent_row(
        db_session,
        (await make_agent(client, tokens, name="Voice Bot", voice_enabled=True))["id"],
    )
    silent = await _agent_row(
        db_session,
        (await make_agent(client, tokens, name="Silent Voice Bot", voice_enabled=True))["id"],
    )
    assert silent.voice_enabled is True  # enabled, but deliberately never used

    await seed_conversation(db_session, voice)

    totals = (await fetch_overview(client, tokens))["totals"]
    assert totals["voice_agents_used"] == 1


# --------------------------------------------------------------------------
# Windowing
# --------------------------------------------------------------------------
async def test_rows_outside_the_window_move_into_previous_totals(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])

    await seed_conversation(db_session, agent, days_ago=2)  # inside a 7-day window
    await seed_conversation(db_session, agent, days_ago=9)  # inside the previous 7 days
    await seed_conversation(db_session, agent, days_ago=40)  # outside both

    overview = await fetch_overview(client, tokens, days=7)
    assert overview["range_days"] == 7
    assert overview["totals"]["conversations"] == 1
    assert overview["previous_totals"]["conversations"] == 1


async def test_daily_series_covers_every_day_including_empty_ones(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])
    await seed_conversation(db_session, agent, days_ago=1, user_messages=2, assistant_messages=2)

    daily = (await fetch_overview(client, tokens, days=7))["daily"]
    assert len(daily) == 7
    # Ascending, contiguous, no gaps.
    days = [point["day"] for point in daily]
    assert days == sorted(days)
    assert days[-1] == datetime.now(UTC).date().isoformat()

    active = [point for point in daily if point["conversations"] > 0]
    assert len(active) == 1
    assert active[0]["messages"] == 4
    assert active[0]["sessions"] == 1
    assert sum(point["conversations"] for point in daily) == 1


async def test_daily_buckets_are_utc_regardless_of_the_database_timezone(client, db_session):
    """Guards a real off-by-one found by running the app.

    `date_trunc('day', <timestamptz>)` truncates in the *session* TimeZone. On
    a database set to Asia/Calcutta (as the dev machine's is) a conversation at
    12:24 UTC on the 5th truncates to IST midnight on the 5th — returned as
    2026-09-04T18:30Z — and reading `.date()` off that puts it on the 4th. The
    spine is built in UTC, so every point shifted a day and, east of UTC, the
    most recent bucket could fall outside the spine and vanish from the chart.

    The other tests here missed it because a uniform one-day shift still lands
    inside the window. This one pins the timezone and asserts the exact day.
    """
    await db_session.execute(text("SET TIME ZONE 'Asia/Calcutta'"))

    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])

    # Late-morning UTC, which is already the *next* day in some zones and the
    # same day in IST — the hour where a session-timezone truncation and a UTC
    # one disagree.
    today = datetime.now(UTC).date()
    at = datetime.combine(today, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
    session = WidgetSession(
        agent_id=agent.id,
        tenant_id=agent.tenant_id,
        origin=ORIGIN,
        expires_at=at + timedelta(hours=12),
        created_at=at,
        updated_at=at,
    )
    db_session.add(session)
    await db_session.flush()
    conversation = Conversation(
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        widget_session_id=session.id,
        last_message_at=at,
        created_at=at,
        updated_at=at,
    )
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content="hello",
            created_at=at,
            updated_at=at,
        )
    )
    await db_session.flush()

    daily = (await fetch_overview(client, tokens, days=7))["daily"]
    active = [point for point in daily if point["conversations"] > 0]
    assert len(active) == 1
    assert active[0]["day"] == today.isoformat()
    assert active[0]["messages"] == 1
    assert active[0]["sessions"] == 1


async def test_days_parameter_is_bounded(client):
    tokens = await register(client)
    assert (
        await client.get(
            f"{PREFIX}/analytics/overview", params={"days": 0}, headers=bearer(tokens)
        )
    ).status_code == 422
    assert (
        await client.get(
            f"{PREFIX}/analytics/overview", params={"days": 91}, headers=bearer(tokens)
        )
    ).status_code == 422


# --------------------------------------------------------------------------
# Breakdowns
# --------------------------------------------------------------------------
async def test_agents_include_idle_ones_and_are_ordered_by_traffic(client, db_session):
    tokens = await register(client)
    busy = await _agent_row(db_session, (await make_agent(client, tokens, name="Busy"))["id"])
    await _agent_row(db_session, (await make_agent(client, tokens, name="Idle"))["id"])

    await seed_conversation(db_session, busy, user_messages=3, assistant_messages=3)

    overview = await fetch_overview(client, tokens)
    assert overview["agents_total"] == 2
    assert [a["name"] for a in overview["agents"]] == ["Busy", "Idle"]
    assert overview["agents"][0]["messages"] == 6
    assert overview["agents"][0]["conversations"] == 1
    assert overview["agents"][1]["messages"] == 0
    assert overview["agents"][1]["last_activity_at"] is None


async def test_agents_active_counts_only_activated_agents(client, db_session):
    tokens = await register(client)
    draft = await make_agent(client, tokens, name="Draft Bot")
    live = await make_agent(client, tokens, name="Live Bot")
    await client.patch(
        f"{PREFIX}/agents/{live['id']}", json={"status": "active"}, headers=bearer(tokens)
    )
    assert draft["status"] == "draft"

    overview = await fetch_overview(client, tokens)
    assert overview["agents_total"] == 2
    assert overview["agents_active"] == 1


async def test_origins_are_grouped_and_ordered_by_session_count(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])

    await seed_conversation(db_session, agent, origin="https://a.example.com")
    await seed_conversation(db_session, agent, origin="https://a.example.com")
    await seed_conversation(db_session, agent, origin="https://b.example.com")

    origins = (await fetch_overview(client, tokens))["origins"]
    assert origins == [
        {"origin": "https://a.example.com", "sessions": 2},
        {"origin": "https://b.example.com", "sessions": 1},
    ]


async def test_knowledge_base_stats_are_current_state_not_windowed(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens))["id"])

    old = _midnight_utc(80)  # far outside any 30-day window
    for status, chars in (("ready", 4_000), ("ready", 1_000), ("failed", None)):
        db_session.add(
            Document(
                tenant_id=agent.tenant_id,
                agent_id=agent.id,
                source_type="text",
                title=f"doc {status} {chars}",
                status=status,
                char_count=chars,
                created_at=old,
                updated_at=old,
            )
        )
    await db_session.flush()

    kb = (await fetch_overview(client, tokens))["knowledge_base"]
    assert kb == {
        "documents": 3,
        "ready": 2,
        "pending": 0,
        "processing": 0,
        "failed": 1,
        "characters": 5_000,
    }


async def test_recent_conversations_are_newest_first_with_their_agent_name(client, db_session):
    tokens = await register(client)
    agent = await _agent_row(db_session, (await make_agent(client, tokens, name="Support"))["id"])

    await seed_conversation(db_session, agent, days_ago=5)
    await seed_conversation(db_session, agent, days_ago=1, user_messages=2, assistant_messages=2)

    recent = (await fetch_overview(client, tokens))["recent_conversations"]
    assert len(recent) == 2
    assert recent[0]["messages"] == 4
    assert recent[0]["agent_name"] == "Support"
    assert recent[0]["last_message_at"] > recent[1]["last_message_at"]


# --------------------------------------------------------------------------
# Quota
# --------------------------------------------------------------------------
async def test_quota_mirrors_the_tenant_and_never_exceeds_100_percent(client, db_session):
    tokens = await register(client)
    me = (await client.get(f"{PREFIX}/auth/me", headers=bearer(tokens))).json()

    quota = (await fetch_overview(client, tokens))["quota"]
    assert quota["plan"] == "free"
    assert quota["quota"] == me["tenant"]["monthly_message_quota"]
    assert quota["used"] == me["tenant"]["messages_used_in_period"]
    assert quota["remaining"] == quota["quota"] - quota["used"]
    assert 0 <= quota["percent_used"] <= 100


async def test_an_empty_workspace_returns_zeroes_rather_than_failing(client):
    tokens = await register(client)
    overview = await fetch_overview(client, tokens)

    assert overview["totals"]["conversations"] == 0
    assert overview["totals"]["input_tokens"] == 0
    assert overview["agents_total"] == 0
    assert overview["knowledge_base"]["documents"] == 0
    assert len(overview["daily"]) == 30
    assert all(point["messages"] == 0 for point in overview["daily"])
