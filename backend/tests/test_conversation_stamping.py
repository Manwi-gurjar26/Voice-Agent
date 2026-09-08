"""last_message_at must actually reach the database.

This file exists because the assertions in test_chat.py could not have caught
the bug it guards. They read the conversation back through the same session
that mutated it, so they pass on the identity-mapped in-memory object even when
nothing was written; and the `get_db` override yields one long-lived session,
so the instance never becomes detached the way it does in production.

In production FastAPI exits `yield` dependencies *before* a StreamingResponse's
body runs, `get_db` closes the session, and closing expunges every instance —
after which `conversation.last_message_at = ...` is a silent no-op. Messages
still persisted (they are added explicitly), so the failure was invisible until
the dashboard tried to show "last seen".

Both tests here expire the identity map before reading, and the second one
reproduces the production lifecycle directly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Conversation
from app.services import chat as chat_service
from app.services import rate_limit
from tests.groq_fakes import install_fake_chat_client
from tests.test_agents import make_agent
from tests.test_auth import bearer, register
from tests.test_chat import make_widget_session, session_auth

PREFIX = settings.api_v1_prefix


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._reset_for_tests()
    yield
    rate_limit._reset_for_tests()


async def _fresh_last_message_at(db_session, conversation_id):
    """Force a real SELECT rather than reading the identity map."""
    db_session.expire_all()
    row = await db_session.scalar(select(Conversation).where(Conversation.id == conversation_id))
    return row.last_message_at


async def test_public_path_persists_last_message_at(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("hi",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hello"},
        headers=session_auth(session),
    )

    assert await _fresh_last_message_at(db_session, conv["id"]) is not None


async def test_preview_path_persists_last_message_at(client, monkeypatch, db_session):
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("hi",))

    conv = (
        await client.post(
            f"{PREFIX}/agents/{agent['id']}/preview/conversations", headers=bearer(tokens)
        )
    ).json()
    await client.post(
        f"{PREFIX}/agents/{agent['id']}/preview/conversations/{conv['id']}/messages",
        json={"content": "hello"},
        headers=bearer(tokens),
    )

    assert await _fresh_last_message_at(db_session, conv["id"]) is not None


async def test_stamp_survives_a_detached_conversation(client, monkeypatch, db_session):
    """The actual production condition, reproduced directly.

    `expunge` puts the conversation in exactly the state `get_db`'s session
    close leaves it in before a streamed body runs. Under the old ORM
    assignment this wrote nothing at all; the stamp must not depend on the
    instance still being attached.
    """
    tokens = await register(client)
    agent = await make_agent(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("hi",))

    created = (
        await client.post(
            f"{PREFIX}/agents/{agent['id']}/preview/conversations", headers=bearer(tokens)
        )
    ).json()
    conversation = await db_session.scalar(
        select(Conversation).where(Conversation.id == created["id"])
    )
    db_session.expunge(conversation)
    assert conversation not in db_session

    await chat_service._touch_last_message_at(db_session, conversation)
    await db_session.commit()

    assert await _fresh_last_message_at(db_session, created["id"]) is not None
