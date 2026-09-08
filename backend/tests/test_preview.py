from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.v1.preview import PREVIEW_ORIGIN
from app.core.config import settings
from app.models import Conversation, WidgetSession
from app.services import rate_limit
from tests.groq_fakes import install_fake_chat_client
from tests.test_agents import make_agent
from tests.test_auth import bearer, register
from tests.test_chat import parse_sse

PREFIX = settings.api_v1_prefix


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._reset_for_tests()
    yield
    rate_limit._reset_for_tests()


async def start_preview(client, tokens, agent_id: str) -> dict:
    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/preview/conversations", headers=bearer(tokens)
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# The two things the public widget path cannot do
# --------------------------------------------------------------------------
async def test_preview_works_on_a_draft_agent(client, monkeypatch):
    """The whole reason this endpoint exists. /public/* refuses any agent that
    is not `active`, which is exactly the agent you want to try first."""
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    assert agent["status"] == "draft"
    install_fake_chat_client(monkeypatch, chunks=("Hi", " there", "!"))

    conv = await start_preview(client, tokens, agent["id"])
    response = await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
        json={"content": "Hello"},
        headers=bearer(tokens),
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    deltas = [data["text"] for event, data in parse_sse(response.text) if event == "delta"]
    assert deltas == ["Hi", " there", "!"]


async def test_preview_needs_no_origin_allowlist_entry(client, monkeypatch):
    """No Origin header at all, and an allowlist that names an unrelated site.
    The public routes would 403; this one is authorised by the session."""
    tokens = await register(client)
    agent = await make_agent(client, tokens, allowed_origins=["https://elsewhere.example.com"])
    install_fake_chat_client(monkeypatch, chunks=("ok",))

    conv = await start_preview(client, tokens, agent["id"])
    response = await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
        json={"content": "Hello"},
        headers=bearer(tokens),
    )
    assert response.status_code == 200


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------
async def test_preview_requires_authentication(client):
    tokens = await register(client)
    agent = await make_agent(client, tokens)

    response = await client.post(f"{PREFIX}/agents/{agent['id']}/preview/conversations")
    assert response.status_code == 401


async def test_another_tenant_cannot_preview_your_agent(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent = await make_agent(client, tokens_a, name="Acme Bot")

    response = await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations", headers=bearer(tokens_b)
    )
    # 404, not 403 — the same shape agent_service.get_agent uses everywhere,
    # so an id belonging to another tenant is indistinguishable from a
    # nonexistent one.
    assert response.status_code == 404


async def test_another_tenants_conversation_is_not_reachable(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent_a = await make_agent(client, tokens_a, name="Acme Bot")
    agent_b = await make_agent(client, tokens_b, name="Globex Bot")
    conv = await start_preview(client, tokens_a, agent_a["id"])

    response = await client.get(
        f"{PREFIX}/agents/{agent_b['id']}/preview/conversations/{conv['id']}/messages",
        headers=bearer(tokens_b),
    )
    assert response.status_code == 404


async def test_a_conversation_cannot_be_used_through_a_different_agent(client):
    """Both agents belong to the caller, so tenant scoping alone would let this
    through — the agent_id in the path has to be part of the check."""
    tokens = await register(client)
    agent_one = await make_agent(client, tokens, name="One")
    agent_two = await make_agent(client, tokens, name="Two")
    conv = await start_preview(client, tokens, agent_one["id"])

    response = await client.get(
        f"{PREFIX}/agents/{agent_two['id']}/preview/conversations/{conv['id']}/messages",
        headers=bearer(tokens),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------
async def test_preview_session_is_tagged_so_it_is_distinguishable(client, db_session):
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    await start_preview(client, tokens, agent["id"])

    session = await db_session.scalar(select(WidgetSession))
    assert session is not None
    assert session.origin == PREVIEW_ORIGIN


async def test_preview_turns_persist_like_any_other_conversation(client, monkeypatch, db_session):
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("The answer is 42.",))

    conv = await start_preview(client, tokens, agent["id"])
    await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
        json={"content": "What is the answer?"},
        headers=bearer(tokens),
    )

    history = (
        await client.get(
            f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
            headers=bearer(tokens),
        )
    ).json()
    assert [m["role"] for m in history["items"]] == ["user", "assistant"]
    assert history["items"][1]["content"] == "The answer is 42."

    row = await db_session.scalar(select(Conversation).where(Conversation.id == conv["id"]))
    assert row is not None
    assert row.last_message_at is not None


async def test_preview_history_survives_a_page_reload(client, monkeypatch):
    """Scoped to tenant+agent rather than to a widget session, so the thread is
    still readable after the browser session that started it is gone."""
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("first reply",))

    conv = await start_preview(client, tokens, agent["id"])
    await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
        json={"content": "hello"},
        headers=bearer(tokens),
    )

    fresh_tokens = (
        await client.post(
            f"{PREFIX}/auth/login",
            json={"email": "owner@acme.example.com", "password": "correct-horse-9-battery"},
        )
    ).json()
    history = (
        await client.get(
            f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
            headers=bearer(fresh_tokens),
        )
    ).json()
    assert len(history["items"]) == 2


# --------------------------------------------------------------------------
# Config and voice
# --------------------------------------------------------------------------
async def test_preview_config_matches_the_public_widget_schema(client):
    tokens = await register(client)
    agent = await make_agent(client, tokens, greeting="Hi from preview")

    config = (
        await client.get(f"{PREFIX}/agents/{agent['id']}/preview/config", headers=bearer(tokens))
    ).json()
    assert config == {
        "name": agent["name"],
        "greeting": "Hi from preview",
        "voice_enabled": False,
        "theme": agent["theme"],
    }
    # The same allowlist the visitor-facing config uses — nothing internal.
    assert "system_prompt" not in config
    assert "allowed_origins" not in config


async def test_voice_preview_is_refused_when_the_agent_has_voice_off(client):
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    assert agent["voice_enabled"] is False
    conv = await start_preview(client, tokens, agent["id"])

    response = await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/voice-messages",
        files={"file": ("recording.webm", b"not-audio", "audio/webm")},
        headers=bearer(tokens),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "voice_not_enabled"
