from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Conversation, Message, Tenant
from app.services import llm
from tests.test_auth import bearer, register
from tests.test_public import ORIGIN, make_active_agent
from tests.groq_fakes import install_fake_chat_client, install_fake_groq_client

PREFIX = settings.api_v1_prefix


# --------------------------------------------------------------------------
# Fake Gemini client — the seam is app.services.llm.get_gemini_client;
# monkeypatching it means production code never changes to run these tests.
# --------------------------------------------------------------------------
class _FakeUsageMetadata:
    def __init__(self, input_tokens: int = 42, output_tokens: int = 7) -> None:
        self.prompt_token_count = input_tokens
        self.candidates_token_count = output_tokens


class _FakeFinishReason:
    def __init__(self, value: str | None) -> None:
        self.value = value


class _FakeCandidate:
    def __init__(self, finish_reason: str | None) -> None:
        self.finish_reason = _FakeFinishReason(finish_reason)


class _FakeGenerateContentResponse:
    """Mirrors the members real code touches on the real SDK's response/chunk
    object: `.text`, `.usage_metadata`, and `.candidates[0].finish_reason`."""

    def __init__(self, text: str, finish_reason: str | None, usage: _FakeUsageMetadata) -> None:
        self.text = text
        self.usage_metadata = usage
        self.candidates = [_FakeCandidate(finish_reason)]


class _FakeGeminiStream:
    def __init__(
        self,
        chunks: tuple[str, ...],
        finish_reason: str = "STOP",
        usage: _FakeUsageMetadata | None = None,
        delay_seconds: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._finish_reason = finish_reason
        self._usage = usage or _FakeUsageMetadata()
        self._delay_seconds = delay_seconds
        self._error = error

    async def __aiter__(self):
        for chunk in self._chunks:
            if self._delay_seconds:
                await asyncio.sleep(self._delay_seconds)
            yield _FakeGenerateContentResponse(chunk, self._finish_reason, self._usage)
        if self._error is not None:
            raise self._error

    async def create(self) -> _FakeGenerateContentResponse:
        """Mirrors the non-streaming client.aio.models.generate_content()
        path used by chat_service.complete_turn (Step 7) — unlike iterating
        the stream, this raises `error` directly, since there are no chunks
        to raise it partway through for a caller that never streams."""
        if self._error is not None:
            raise self._error
        return _FakeGenerateContentResponse(
            "".join(self._chunks), self._finish_reason, self._usage
        )


class _FakeModelsResource:
    def __init__(self, factory) -> None:
        self._factory = factory
        self.last_kwargs: dict | None = None

    async def generate_content_stream(self, **kwargs):
        self.last_kwargs = kwargs
        return self._factory(**kwargs)

    async def generate_content(self, **kwargs) -> _FakeGenerateContentResponse:
        self.last_kwargs = kwargs
        return await self._factory(**kwargs).create()


class _FakeAio:
    def __init__(self, models: _FakeModelsResource) -> None:
        self.models = models


class FakeGeminiClient:
    def __init__(self, factory) -> None:
        self.aio = _FakeAio(_FakeModelsResource(factory))


def install_fake_gemini_client(monkeypatch, chunks=("Hello", ", ", "world!"), **stream_kwargs):
    """Patch app.services.llm.get_gemini_client — the *fallback* provider
    for typed chat. Returns the fake client so tests can inspect what was
    requested."""

    def factory(**_kwargs):
        return _FakeGeminiStream(chunks, **stream_kwargs)

    fake_client = FakeGeminiClient(factory)
    monkeypatch.setattr(llm, "get_gemini_client", lambda: fake_client)
    return fake_client


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
async def make_widget_session(client, tokens, **agent_overrides) -> tuple[dict, dict]:
    agent = await make_active_agent(client, tokens, **agent_overrides)
    response = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200, response.text
    return agent, response.json()


def session_auth(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['session_token']}", "Origin": ORIGIN}


def parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse `event: X\\ndata: Y\\n\\n` blocks into (event, json_data) pairs."""
    import json

    events = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        event = event_line.removeprefix("event: ")
        data = json.loads(data_line.removeprefix("data: "))
        events.append((event, data))
    return events


# --------------------------------------------------------------------------
# Conversation creation and ownership
# --------------------------------------------------------------------------
async def test_create_conversation_returns_an_id(client):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)

    response = await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    assert response.status_code == 201
    assert "id" in response.json()


async def test_conversation_is_scoped_to_the_creating_session(client):
    tokens = await register(client)
    agent, session_a = await make_widget_session(client, tokens)
    # A second visitor session for the SAME agent.
    session_b_resp = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    session_b = session_b_resp.json()

    created = await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session_a))
    conversation_id = created.json()["id"]

    response = await client.get(
        f"{PREFIX}/public/conversations/{conversation_id}/messages",
        headers=session_auth(session_b),
    )
    # 404, not 403 — session_b's visitor should not learn this id exists.
    assert response.status_code == 404


async def test_unknown_conversation_id_is_404(client):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)

    response = await client.get(
        f"{PREFIX}/public/conversations/00000000-0000-0000-0000-000000000000/messages",
        headers=session_auth(session),
    )
    assert response.status_code == 404


async def test_conversations_require_a_widget_session(client):
    response = await client.post(f"{PREFIX}/public/conversations", headers={"Origin": ORIGIN})
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Sending a message — happy path
# --------------------------------------------------------------------------
async def test_send_message_streams_deltas_and_a_done_event(client, monkeypatch):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("Hi", " there", "!"))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()

    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "Hello"},
        headers=session_auth(session),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    deltas = [data["text"] for event, data in events if event == "delta"]
    assert deltas == ["Hi", " there", "!"]

    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    assert done_events[0]["usage"] == {"input_tokens": 42, "output_tokens": 7}
    assert done_events[0]["stop_reason"] == "stop"


async def test_sent_message_and_reply_are_both_persisted(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("The answer is 42.",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "What is the answer?"},
        headers=session_auth(session),
    )

    rows = list(
        await db_session.scalars(
            select(Message)
            .where(Message.conversation_id == conv["id"])
            .order_by(Message.created_at)
        )
    )
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "What is the answer?"
    assert rows[1].content == "The answer is 42."
    assert rows[1].input_tokens == 42
    assert rows[1].output_tokens == 7
    assert rows[0].input_tokens is None  # only assistant rows carry usage


async def test_conversation_last_message_at_is_updated(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("Ok",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    assert (
        await db_session.scalar(select(Conversation).where(Conversation.id == conv["id"]))
    ).last_message_at is None

    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    row = await db_session.scalar(select(Conversation).where(Conversation.id == conv["id"]))
    assert row.last_message_at is not None


async def test_message_list_endpoint_returns_full_history(client, monkeypatch):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("Reply one",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "Question one"},
        headers=session_auth(session),
    )

    listing = await client.get(
        f"{PREFIX}/public/conversations/{conv['id']}/messages", headers=session_auth(session)
    )
    assert listing.status_code == 200
    contents = [(m["role"], m["content"]) for m in listing.json()["items"]]
    assert contents == [("user", "Question one"), ("assistant", "Reply one")]


async def test_the_llm_is_called_with_the_agents_configuration(client, monkeypatch):
    tokens = await register(client)
    agent, session = await make_widget_session(
        client, tokens, effort="xhigh", max_output_tokens=1024
    )
    fake_client = install_fake_chat_client(monkeypatch, chunks=("ok",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    kwargs = fake_client.last_kwargs
    assert kwargs["model"] == agent["model"]
    assert kwargs["max_tokens"] == 1024
    assert kwargs["stream"] is True
    assert kwargs["messages"][0] == {"role": "system", "content": agent["system_prompt"]}
    # No temperature/top_p/top_k anywhere — this app deliberately exposes no
    # sampling knobs. (`effort` only reaches the Gemini fallback, which has a
    # thinking budget; Groq has no equivalent.)
    assert "temperature" not in kwargs
    assert "top_p" not in kwargs


async def test_multi_turn_history_alternates_correctly(client, monkeypatch):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    fake_client = install_fake_chat_client(monkeypatch, chunks=("Reply",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()

    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "First question"},
        headers=session_auth(session),
    )
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "Second question"},
        headers=session_auth(session),
    )

    messages = fake_client.last_kwargs["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "First question"
    assert messages[-1]["content"] == "Second question"


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------
async def test_gemini_error_surfaces_as_an_sse_error_event_not_a_500(client, monkeypatch):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=(), error=RuntimeError("boom"))
    install_fake_gemini_client(monkeypatch, chunks=(), error=RuntimeError("gemini down too"))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")  # fallback is configured

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    # Headers are already committed to a 200 once streaming starts — failure
    # can only be communicated inside the stream, never via HTTP status.
    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "llm_error"


async def test_a_failed_turn_still_persists_the_user_message(client, monkeypatch, db_session):
    """Quota and the user's own message must survive a Gemini-side failure —
    otherwise a flaky LLM call would let a client retry for free."""
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=(), error=RuntimeError("boom"))
    monkeypatch.setattr(settings, "gemini_api_key", None)  # no fallback configured

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    rows = list(await db_session.scalars(select(Message)))
    assert len(rows) == 1
    assert rows[0].role == "user"


async def test_a_failed_turn_still_leaves_alternating_history_for_the_next_message(
    client, monkeypatch, db_session
):
    """After a failed turn the conversation holds a lone unanswered user
    message, and the next message has to carry it along so the reply still
    has that context. Groq (OpenAI-shaped) accepts consecutive same-role
    messages, so unlike the Gemini fallback they are not merged."""
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=(), error=RuntimeError("boom"))
    monkeypatch.setattr(settings, "gemini_api_key", None)  # no fallback configured

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "first (will fail)"},
        headers=session_auth(session),
    )

    # Second attempt succeeds.
    fake_client = install_fake_chat_client(monkeypatch, chunks=("ok",))
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "second (will succeed)"},
        headers=session_auth(session),
    )

    messages = fake_client.last_kwargs["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "user"]
    assert messages[1]["content"] == "first (will fail)"
    assert messages[2]["content"] == "second (will succeed)"


async def test_empty_message_is_rejected(client, monkeypatch):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch)

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": ""},
        headers=session_auth(session),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Quota enforcement
# --------------------------------------------------------------------------
async def test_quota_exceeded_surfaces_as_an_sse_error_and_saves_nothing(
    client, monkeypatch, db_session
):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("should not be reached",))

    tenant = await db_session.scalar(select(Tenant))
    tenant.monthly_message_quota = 0
    await db_session.commit()

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert len(events) == 1
    assert events[0][0] == "error"
    assert events[0][1]["code"] == "quota_exceeded"

    rows = list(await db_session.scalars(select(Message)))
    assert rows == []


async def test_quota_allows_exactly_the_configured_number_of_messages(
    client, monkeypatch, db_session
):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("ok",))

    tenant = await db_session.scalar(select(Tenant))
    tenant.monthly_message_quota = 2
    await db_session.commit()

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()

    outcomes = []
    for i in range(3):
        response = await client.post(
            f"{PREFIX}/public/conversations/{conv['id']}/messages",
            json={"content": f"message {i}"},
            headers=session_auth(session),
        )
        events = parse_sse(response.text)
        outcomes.append(events[-1][0])

    assert outcomes == ["done", "done", "error"]


async def test_quota_period_resets_after_the_rolling_window(client, monkeypatch, db_session):
    from datetime import datetime, timedelta, timezone

    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("ok",))

    tenant = await db_session.scalar(select(Tenant))
    tenant.monthly_message_quota = 1
    tenant.messages_used_in_period = 1  # already at the limit
    tenant.period_started_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.commit()

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    events = parse_sse(response.text)
    assert events[-1][0] == "done"


# --------------------------------------------------------------------------
# Rate limiting shares the Step 3 per-agent-per-IP bucket
# --------------------------------------------------------------------------
async def test_sending_messages_is_rate_limited(client, monkeypatch):
    # rate_limit_per_minute isn't an AgentCreate field (only AgentUpdate), so
    # it must be set via PATCH after creation — passing it to make_active_agent
    # (which POSTs to /agents) would be silently ignored, same as Step 3.
    from app.services import rate_limit

    rate_limit._reset_for_tests()
    tokens = await register(client)
    from tests.test_public import make_active_agent

    agent = await make_active_agent(client, tokens)
    await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"rate_limit_per_minute": 1}, headers=bearer(tokens)
    )

    # Session creation draws from the SAME shared per-agent-per-IP bucket
    # (Step 3) as conversation creation does — so it counts as this test's
    # first call against the newly-tightened limit of 1.
    session_resp = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    assert session_resp.status_code == 200
    session = session_resp.json()

    install_fake_chat_client(monkeypatch, chunks=("ok",))
    conv_resp = await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    assert conv_resp.status_code == 429

    rate_limit._reset_for_tests()


# --------------------------------------------------------------------------
# Streaming must not be buffered by our middleware stack
# --------------------------------------------------------------------------
async def test_response_streams_incrementally_not_all_at_once(app, monkeypatch):
    """Regression guard: BaseHTTPMiddleware is documented, in some Starlette
    versions, to fully buffer a StreamingResponse before the client sees any
    of it — which would silently defeat the entire point of streaming (the
    widget would stare at a blank bubble for the full response time, then get
    everything at once). This measures real inter-chunk arrival timing over a
    REAL socket, not just that the final content is correct.

    httpx's in-process ASGITransport (what the `client` fixture uses
    everywhere else in this suite) cannot answer this question — it was
    confirmed experimentally to coalesce a StreamingResponse's body before
    handing it to `.aiter_bytes()`, regardless of how the server actually
    streamed it, producing a false "buffered!" signal even though a live
    smoke test against a real running uvicorn process (real socket, real
    curl trace) showed correct ~500ms-spaced incremental delivery through
    this exact middleware stack. So this test runs a real uvicorn `Server`
    on a real loopback socket, in-process (same event loop, so monkeypatching
    the fake Gemini client still works) — the only way to get a
    trustworthy answer inside the automated suite.
    """
    import httpx
    import uvicorn

    install_fake_chat_client(monkeypatch, chunks=("a", "b", "c"), delay_seconds=0.2)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="critical")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as real_client:
            tokens = await register(real_client)
            _agent, session = await make_widget_session(real_client, tokens)
            conv = (
                await real_client.post(
                    f"{PREFIX}/public/conversations", headers=session_auth(session)
                )
            ).json()

            arrival_times: list[float] = []
            started = time.monotonic()
            async with real_client.stream(
                "POST",
                f"{PREFIX}/public/conversations/{conv['id']}/messages",
                json={"content": "hi"},
                headers=session_auth(session),
            ) as response:
                async for chunk in response.aiter_bytes():
                    if chunk.strip():
                        arrival_times.append(time.monotonic() - started)
    finally:
        server.should_exit = True
        await serve_task

    assert len(arrival_times) >= 3, arrival_times
    # If buffered, ALL chunks arrive together near the total ~0.6s delay. If
    # streamed, the first chunk arrives near ~0.2s — well before the last.
    assert arrival_times[0] < 0.35, (
        f"first chunk arrived at {arrival_times[0]:.2f}s — looks buffered, "
        f"not streamed (all arrival times: {arrival_times})"
    )
    assert arrival_times[-1] - arrival_times[0] > 0.2, (
        "all chunks arrived within the same instant — looks buffered, "
        f"not streamed (arrival times: {arrival_times})"
    )


# --------------------------------------------------------------------------
# RAG: retrieval augments the system prompt and produces citations
# --------------------------------------------------------------------------
def install_fake_embeddings(monkeypatch, vector: list[float] | None = None):
    """Deterministic stand-in for the real model — test_embeddings.py
    separately verifies the real model produces sensible similarity scores;
    these tests only need embeddings to exist and be controllable."""
    from app.services import embeddings

    async def fake_embed_query(text: str) -> list[float]:
        return vector or [1.0, 0.0]

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [vector or [1.0, 0.0] for _ in texts]

    monkeypatch.setattr(embeddings, "embed_query", fake_embed_query)
    monkeypatch.setattr(embeddings, "embed_texts", fake_embed_texts)


async def _add_document_with_chunk(db_session, agent_id, tenant_id, *, title: str, content: str, embedding: list[float]):
    from app.models import Chunk, Document

    document = Document(
        tenant_id=tenant_id, agent_id=agent_id, source_type="text", title=title, status="ready"
    )
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        Chunk(
            document_id=document.id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            chunk_index=0,
            content=content,
            embedding=embedding,
        )
    )
    await db_session.commit()
    return document


async def test_relevant_chunks_are_injected_into_the_system_prompt(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Agent as AgentModel

    tokens = await register(client)
    agent, session = await make_widget_session(client, tokens)
    agent_row = await db_session.scalar(select(AgentModel).where(AgentModel.id == agent["id"]))

    install_fake_embeddings(monkeypatch, vector=[1.0, 0.0])
    await _add_document_with_chunk(
        db_session,
        agent_row.id,
        agent_row.tenant_id,
        title="Business Hours",
        content="We are open 9am to 5pm, Monday through Friday.",
        embedding=[1.0, 0.0],  # identical to the fake query vector: perfect match
    )

    fake_client = install_fake_chat_client(monkeypatch, chunks=("We're open 9-5.",))
    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "What are your hours?"},
        headers=session_auth(session),
    )

    sent_system = fake_client.last_kwargs["messages"][0]["content"]
    assert "We are open 9am to 5pm" in sent_system
    assert "Business Hours" in sent_system
    assert sent_system.startswith(agent["system_prompt"])  # base prompt preserved, not replaced


async def test_response_includes_citations_when_retrieval_matched(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Agent as AgentModel

    tokens = await register(client)
    agent, session = await make_widget_session(client, tokens)
    agent_row = await db_session.scalar(select(AgentModel).where(AgentModel.id == agent["id"]))

    install_fake_embeddings(monkeypatch, vector=[1.0, 0.0])
    document = await _add_document_with_chunk(
        db_session,
        agent_row.id,
        agent_row.tenant_id,
        title="Refund Policy",
        content="Refunds within 30 days of purchase.",
        embedding=[1.0, 0.0],
    )

    install_fake_chat_client(monkeypatch, chunks=("Refunds are available within 30 days.",))
    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "What's your refund policy?"},
        headers=session_auth(session),
    )

    events = parse_sse(response.text)
    done = next(data for event, data in events if event == "done")
    assert done["citations"] == [{"document_id": str(document.id), "title": "Refund Policy"}]


async def test_citations_are_persisted_on_the_assistant_message(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Agent as AgentModel, Message

    tokens = await register(client)
    agent, session = await make_widget_session(client, tokens)
    agent_row = await db_session.scalar(select(AgentModel).where(AgentModel.id == agent["id"]))

    install_fake_embeddings(monkeypatch, vector=[1.0, 0.0])
    document = await _add_document_with_chunk(
        db_session,
        agent_row.id,
        agent_row.tenant_id,
        title="Shipping Info",
        content="We ship within 2 business days.",
        embedding=[1.0, 0.0],
    )
    install_fake_chat_client(monkeypatch, chunks=("2 business days.",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "How fast is shipping?"},
        headers=session_auth(session),
    )

    assistant_row = await db_session.scalar(
        select(Message).where(Message.conversation_id == conv["id"], Message.role == "assistant")
    )
    assert assistant_row.citations == [{"document_id": str(document.id), "title": "Shipping Info"}]

    # And the history endpoint surfaces them too.
    listing = await client.get(
        f"{PREFIX}/public/conversations/{conv['id']}/messages", headers=session_auth(session)
    )
    assistant_item = next(m for m in listing.json()["items"] if m["role"] == "assistant")
    assert assistant_item["citations"] == [{"document_id": str(document.id), "title": "Shipping Info"}]


async def test_multiple_matching_chunks_from_the_same_document_cite_it_once(
    client, monkeypatch, db_session
):
    from sqlalchemy import select

    from app.models import Agent as AgentModel, Chunk, Document

    tokens = await register(client)
    agent, session = await make_widget_session(client, tokens)
    agent_row = await db_session.scalar(select(AgentModel).where(AgentModel.id == agent["id"]))

    install_fake_embeddings(monkeypatch, vector=[1.0, 0.0])
    document = Document(
        tenant_id=agent_row.tenant_id,
        agent_id=agent_row.id,
        source_type="text",
        title="FAQ",
        status="ready",
    )
    db_session.add(document)
    await db_session.flush()
    for i, text in enumerate(["First relevant chunk.", "Second relevant chunk."]):
        db_session.add(
            Chunk(
                document_id=document.id,
                tenant_id=agent_row.tenant_id,
                agent_id=agent_row.id,
                chunk_index=i,
                content=text,
                embedding=[1.0, 0.0],
            )
        )
    await db_session.commit()

    install_fake_chat_client(monkeypatch, chunks=("Answer.",))
    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "Tell me something"},
        headers=session_auth(session),
    )

    done = next(data for event, data in parse_sse(response.text) if event == "done")
    assert done["citations"] == [{"document_id": str(document.id), "title": "FAQ"}]


async def test_no_knowledge_base_means_unmodified_prompt_and_no_citations(client, monkeypatch):
    """An agent with zero documents should behave exactly as it did before
    Step 5 — plain system prompt, no citations, and (per agent_has_chunks)
    no embedding call made at all."""
    tokens = await register(client)
    agent, session = await make_widget_session(client, tokens)

    embed_calls = []

    async def tracking_embed_query(text: str) -> list[float]:
        embed_calls.append(text)
        return [1.0, 0.0]

    from app.services import embeddings

    monkeypatch.setattr(embeddings, "embed_query", tracking_embed_query)

    fake_client = install_fake_chat_client(monkeypatch, chunks=("Just an answer.",))
    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "Anything?"},
        headers=session_auth(session),
    )

    assert fake_client.last_kwargs["messages"][0]["content"] == agent["system_prompt"]
    done = next(data for event, data in parse_sse(response.text) if event == "done")
    assert done["citations"] == []
    assert embed_calls == []  # agent_has_chunks short-circuited before any embedding call


async def test_irrelevant_question_below_similarity_threshold_gets_no_citations(
    client, monkeypatch, db_session
):
    from sqlalchemy import select

    from app.models import Agent as AgentModel

    tokens = await register(client)
    agent, session = await make_widget_session(client, tokens)
    agent_row = await db_session.scalar(select(AgentModel).where(AgentModel.id == agent["id"]))

    # Query vector is orthogonal to the stored chunk's vector: cosine
    # similarity 0.0, below the default retrieval_min_similarity.
    await _add_document_with_chunk(
        db_session,
        agent_row.id,
        agent_row.tenant_id,
        title="Unrelated Doc",
        content="Some unrelated content.",
        embedding=[0.0, 1.0],
    )
    install_fake_embeddings(monkeypatch, vector=[1.0, 0.0])
    install_fake_chat_client(monkeypatch, chunks=("An answer.",))

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "Unrelated question"},
        headers=session_auth(session),
    )

    done = next(data for event, data in parse_sse(response.text) if event == "done")
    assert done["citations"] == []


# --------------------------------------------------------------------------
# Groq -> Gemini fallback
#
# Typed chat runs on Groq (Gemini's free tier allows only 20 requests per day
# per model, which stopped customers' chatbots answering mid-afternoon).
# Gemini stays on as a stand-in for when Groq itself is unavailable.
# --------------------------------------------------------------------------
async def test_typed_chat_falls_back_to_gemini_when_groq_is_unavailable(client, monkeypatch):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=(), error=RuntimeError("groq unavailable"))
    install_fake_gemini_client(monkeypatch, chunks=("We are open 9 to 5.",))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "what are your hours?"},
        headers=session_auth(session),
    )

    assert response.status_code == 200
    events = parse_sse(response.text)
    kinds = [name for name, _ in events]
    assert "error" not in kinds
    assert kinds[-1] == "done"
    spoken = "".join(payload["text"] for name, payload in events if name == "delta")
    assert "open 9 to 5" in spoken


async def test_the_fallback_reply_is_persisted_like_any_other(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=(), error=RuntimeError("groq unavailable"))
    install_fake_gemini_client(monkeypatch, chunks=("Fallback answer.",))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    rows = list(await db_session.scalars(select(Message).order_by(Message.created_at)))
    assert [r.role for r in rows] == ["user", "assistant"]
    assert "Fallback answer." in rows[1].content


async def test_a_partly_streamed_reply_does_not_restart_on_the_fallback(client, monkeypatch):
    """Text already sent to the browser can't be un-sent — retrying would
    show the visitor the beginning of the answer twice."""
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)
    install_fake_chat_client(monkeypatch, chunks=("Half an answer",), error=RuntimeError("died midway"))
    install_fake_gemini_client(monkeypatch, chunks=("A completely different answer.",))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")

    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv['id']}/messages",
        json={"content": "hi"},
        headers=session_auth(session),
    )

    events = parse_sse(response.text)
    assert events[-1][0] == "error"
    assert "completely different" not in response.text
