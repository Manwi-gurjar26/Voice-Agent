"""Conversation creation, message persistence, and the Gemini streaming turn."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, NotFoundError, QuotaExceededError
from app.models import Agent, Chunk, Conversation, Message
from app.models.enums import EffortLevel
from app.models.widget_session import WidgetSession
from app.services import embeddings, groq_llm, llm
from app.services.quota import check_and_consume_quota
from app.services.retrieval import agent_has_chunks, find_relevant_chunks

logger = logging.getLogger(__name__)

# Voice replies only (see complete_turn) — typed chat stays on the
# per-agent Gemini model. Explicit request to pipeline voice through Groq
# instead of Gemini/Gemini Live.
GROQ_VOICE_MODEL = "llama-3.1-8b-instant"

# Fish Audio's free TTS tier synthesizes at roughly ~20ms/char (confirmed
# live: 58 chars ~1.7s, 534 chars ~10.5s) — a reply sized for on-screen
# reading (agent.max_output_tokens, up to 2048 by default) can take a
# minute or more to speak, which reads as "the voice assistant is broken"
# long before it actually replies. Voice replies are capped far shorter
# and steered toward spoken-style brevity, independent of the agent's
# text-chat length setting.
_VOICE_MAX_TOKENS = 120


def _voice_instruction() -> str:
    """Spoken-turn guidance appended to the agent's own system prompt.

    The language is stated explicitly: a transcript that came back in the
    wrong language would otherwise drag the reply along with it, and the
    visitor hears an answer in a language they never used.
    """
    return (
        "\n\nThis reply will be converted to speech and read aloud, so keep it "
        "brief and conversational — at most 2-3 short sentences, no lists, "
        f"tables, or markdown formatting. Always reply in "
        f"{settings.voice_language_name}, whatever language the question "
        "appears to be in."
    )

# Defensive cap on how much history we load and resend to the model per turn
# — not a product-facing pagination limit. A conversation this long is
# already unusual; this exists so one doesn't grow the request payload
# unboundedly.
MAX_HISTORY_MESSAGES = 500

# Gemini's thinking_budget is a raw token count, not a named level — these
# values span what gemini-2.5 flash/pro both support. 128 (not 0) is the
# floor because gemini-2.5-pro cannot fully disable thinking (only flash
# accepts 0), so `low` stays safe regardless of which model an agent is
# configured with. EffortLevel itself is unchanged from the Claude version
# (see its docstring) — only this mapping is new.
_THINKING_BUDGET_BY_EFFORT: dict[EffortLevel, int] = {
    EffortLevel.LOW: 128,
    EffortLevel.MEDIUM: 2048,
    EffortLevel.HIGH: 8192,
    EffortLevel.XHIGH: 16384,
    EffortLevel.MAX: 24576,
}

# This app stores "assistant"; Gemini's API expects "model".
_GEMINI_ROLE = {"user": "user", "assistant": "model"}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def create_conversation(db: AsyncSession, session: WidgetSession) -> Conversation:
    conversation = Conversation(
        tenant_id=session.tenant_id,
        agent_id=session.agent_id,
        widget_session_id=session.id,
    )
    db.add(conversation)
    await db.commit()
    return conversation


async def get_owned_conversation(
    db: AsyncSession, session: WidgetSession, conversation_id: uuid.UUID
) -> Conversation:
    """Fetch a conversation, scoped to the CURRENT widget session.

    Scoping by widget_session_id — not just tenant/agent — means one
    visitor's browser session can never read or post into another visitor's
    thread, even for the same agent. 404, not 403: consistent with every
    other ownership check in this app, it doesn't confirm the id exists to a
    session that doesn't own it.
    """
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.widget_session_id == session.id,
        )
    )
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


async def list_messages(db: AsyncSession, conversation: Conversation) -> list[Message]:
    rows = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
        .limit(MAX_HISTORY_MESSAGES)
    )
    return list(rows)


def _build_gemini_contents(history: list[Message]) -> list[types.Content]:
    """Collapse consecutive same-role rows into alternating API turns, then
    map this app's stored roles (user/assistant) to Gemini's (user/model).

    Rows are normally already alternating — one user message triggers exactly
    one persisted assistant reply — but if a prior turn's Gemini call failed
    after the user message was saved (see stream_turn), the next user message
    lands right after another user row. Gemini's API rejects non-alternating
    roles outright, so this merges runs of the same role into a single turn
    rather than erroring on the very next message after any failure.
    """
    turns: list[dict] = []
    for row in history:
        role = _GEMINI_ROLE[row.role]
        if turns and turns[-1]["role"] == role:
            turns[-1]["text"] += f"\n\n{row.content}"
        else:
            turns.append({"role": role, "text": row.content})
    return [
        types.Content(role=turn["role"], parts=[types.Part.from_text(text=turn["text"])])
        for turn in turns
    ]


def _augment_system_prompt(base_prompt: str, chunks: list[Chunk]) -> str:
    """Appends retrieved knowledge-base excerpts to the agent's system
    prompt. Only called when retrieval found at least one chunk above the
    similarity threshold — an agent with no knowledge base, or a question
    with no relevant match, gets the plain configured prompt, unchanged."""
    sources = "\n\n".join(f"[Source: {c.document.title}]\n{c.content}" for c in chunks)
    return (
        f"{base_prompt}\n\n---\n"
        "You have access to the following excerpts from this business's "
        "knowledge base. Use them to answer the visitor's question when "
        "relevant, and say so honestly if the knowledge base doesn't cover "
        "it rather than guessing.\n\n"
        f"{sources}"
    )


def _build_groq_messages(system_prompt: str, history: list[Message]) -> list[dict]:
    """Groq's chat completions API is OpenAI-shaped: a flat message list
    with the system prompt as its own leading message, not Gemini's separate
    system_instruction + alternating-role Content list. Unlike
    _build_gemini_contents, this doesn't collapse consecutive same-role rows
    — OpenAI-compatible APIs are documented to tolerate non-alternating
    roles, unlike Gemini's stricter requirement, though this hasn't been
    exercised against a failed-prior-turn edge case the way Gemini's version
    was."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for row in history:
        role = "assistant" if row.role == "assistant" else "user"
        messages.append({"role": role, "content": row.content})
    return messages


def _citations_from_chunks(chunks: list[Chunk]) -> list[dict] | None:
    """Deduplicated by document — several chunks from the same document
    should produce one citation entry, not one per chunk."""
    if not chunks:
        return None
    seen: dict[uuid.UUID, dict] = {}
    for chunk in chunks:
        seen.setdefault(
            chunk.document_id,
            {"document_id": str(chunk.document_id), "title": chunk.document.title},
        )
    return list(seen.values())


def _generation_config(agent: Agent, system_prompt: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=agent.max_output_tokens,
        thinking_config=types.ThinkingConfig(
            thinking_budget=_THINKING_BUDGET_BY_EFFORT[agent.effort]
        ),
    )


async def _prepare_turn(
    db: AsyncSession, conversation: Conversation, agent: Agent, user_content: str
) -> tuple[str, list[types.Content], list[Message], list[Chunk]]:
    """Shared prep for both stream_turn and complete_turn: enforce quota,
    persist the user message, run retrieval, and build the Gemini contents
    list. Raises QuotaExceededError (already rolled back) on quota failure —
    callers decide how to surface that (an SSE event vs a JSON error).

    Quota is consumed *before* calling Gemini, unconditionally, with no
    refund if the call then fails. That's a deliberate cost-control choice,
    not an oversight: origin allowlisting (Step 3) can't stop a scripted
    client with a valid public_key from forging requests, so the quota
    counter needs to reflect attempted usage, not just successful usage, or
    a client could bypass it by triggering (and abandoning) failing calls.
    """
    try:
        await check_and_consume_quota(db, conversation.tenant_id)
    except QuotaExceededError:
        await db.rollback()
        raise

    user_message = Message(conversation_id=conversation.id, role="user", content=user_content)
    db.add(user_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    # Commit now, not just at end-of-request: the user's message and their
    # quota consumption must survive even if the Gemini call below fails.
    await db.commit()

    # Retrieval: skip the embedding call entirely if this agent has no
    # knowledge base yet — the common case for a newly created agent.
    relevant_chunks: list[Chunk] = []
    if await agent_has_chunks(db, agent.id):
        query_embedding = await embeddings.embed_query(user_content)
        relevant_chunks = await find_relevant_chunks(
            db,
            agent.id,
            query_embedding,
            top_k=settings.retrieval_top_k,
            min_similarity=settings.retrieval_min_similarity,
        )

    system_prompt = (
        _augment_system_prompt(agent.system_prompt, relevant_chunks)
        if relevant_chunks
        else agent.system_prompt
    )

    history = await list_messages(db, conversation)
    gemini_contents = _build_gemini_contents(history)
    return system_prompt, gemini_contents, history, relevant_chunks


async def _stream_groq_reply(
    system_prompt: str, history: list[Message], agent: Agent, stats: dict
) -> AsyncIterator[str]:
    """Typed chat's primary provider.

    Groq, not Gemini: Gemini's free tier allows only 20 generate-content
    requests per day per model (confirmed from a live 429: quotaId
    GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue 20), after
    which a customer's chatbot stops answering for the rest of the day.
    """
    client = groq_llm.get_groq_client()
    stream = await client.chat.completions.create(
        model=agent.model,
        messages=_build_groq_messages(system_prompt, history),
        max_tokens=agent.max_output_tokens,
        stream=True,
    )
    async for chunk in stream:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            stats["input_tokens"] = usage.prompt_tokens
            stats["output_tokens"] = usage.completion_tokens
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue
        choice = choices[0]
        if getattr(choice, "finish_reason", None):
            stats["finish_reason"] = choice.finish_reason
        delta = getattr(choice, "delta", None)
        text = getattr(delta, "content", None) if delta is not None else None
        if text:
            yield text


async def _stream_gemini_reply(
    gemini_contents: list[types.Content], system_prompt: str, agent: Agent, stats: dict
) -> AsyncIterator[str]:
    """Fallback for when Groq is unavailable, used only if a Gemini key is
    configured. Runs on its own configured model, since agent.model now names
    a Groq model."""
    client = llm.get_gemini_client()
    stream = await client.aio.models.generate_content_stream(
        model=settings.gemini_fallback_model,
        contents=gemini_contents,
        config=_generation_config(agent, system_prompt),
    )
    async for chunk in stream:
        if chunk.text:
            yield chunk.text
        usage = chunk.usage_metadata
        if usage is not None:
            stats["input_tokens"] = usage.prompt_token_count
            stats["output_tokens"] = usage.candidates_token_count
        if chunk.candidates:
            reason = chunk.candidates[0].finish_reason
            stats["finish_reason"] = reason.value if reason is not None else None


async def stream_turn(
    db: AsyncSession, conversation: Conversation, agent: Agent, user_content: str
) -> AsyncIterator[str]:
    """Persist the user message, enforce quota, call Gemini, and stream SSE.

    Yields SSE-formatted (`event: ...\\ndata: ...\\n\\n`) chunks — pass this
    directly to `StreamingResponse(..., media_type="text/event-stream")`.
    """
    try:
        system_prompt, gemini_contents, history, relevant_chunks = await _prepare_turn(
            db, conversation, agent, user_content
        )
    except QuotaExceededError as exc:
        yield _sse("error", {"code": exc.code, "message": exc.message})
        return

    accumulated = ""
    stats: dict = {"input_tokens": 0, "output_tokens": 0, "finish_reason": None}
    llm_error = _sse(
        "error",
        {
            "code": "llm_error",
            "message": "The assistant is temporarily unavailable. Please try again.",
        },
    )
    try:
        async for text in _stream_groq_reply(system_prompt, history, agent, stats):
            accumulated += text
            yield _sse("delta", {"text": text})
    except Exception:
        logger.exception("Groq call failed for conversation %s", conversation.id)
        # Text already sent to the browser can't be un-sent, so only a turn
        # that produced nothing may be retried on the other provider.
        if accumulated or not settings.gemini_api_key:
            yield llm_error
            return
        try:
            async for text in _stream_gemini_reply(
                gemini_contents, system_prompt, agent, stats
            ):
                accumulated += text
                yield _sse("delta", {"text": text})
        except Exception:
            logger.exception("Gemini fallback also failed for conversation %s", conversation.id)
            yield llm_error
            return

    input_tokens = stats["input_tokens"]
    output_tokens = stats["output_tokens"]
    finish_reason = stats["finish_reason"]

    citations = _citations_from_chunks(relevant_chunks)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=accumulated,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        citations=citations,
    )
    db.add(assistant_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    await db.commit()

    yield _sse(
        "done",
        {
            "message_id": str(assistant_message.id),
            "stop_reason": finish_reason,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            "citations": citations or [],
        },
    )


async def complete_turn(
    db: AsyncSession, conversation: Conversation, agent: Agent, user_content: str
) -> Message:
    """Non-streaming twin of stream_turn, used by the voice endpoint (Step 7):
    a spoken turn needs the full reply text before TTS can run, so there is
    nothing to stream to the caller. Raises AppError on quota/LLM failure
    instead of yielding an SSE error event — this returns a normal JSON
    response, not a stream.

    Runs on Groq's llama-3.1-8b-instant, not the agent's configured Gemini
    model — an explicit request to keep voice's reply generation on Groq
    while typed messages (stream_turn) stay on Gemini. Retrieval, quota, and
    citation handling are unchanged and identical to stream_turn's — only
    which LLM produces the reply text differs.
    """
    try:
        system_prompt, _gemini_contents, history, relevant_chunks = await _prepare_turn(
            db, conversation, agent, user_content
        )
    except QuotaExceededError as exc:
        raise AppError(exc.message, code=exc.code, status_code=exc.status_code) from exc

    try:
        client = groq_llm.get_groq_client()
        response = await client.chat.completions.create(
            model=GROQ_VOICE_MODEL,
            messages=_build_groq_messages(system_prompt + _voice_instruction(), history),
            max_tokens=min(agent.max_output_tokens, _VOICE_MAX_TOKENS),
        )
    except Exception as exc:
        logger.exception("Groq call failed for conversation %s", conversation.id)
        raise AppError(
            "The assistant is temporarily unavailable. Please try again.",
            code="llm_error",
            status_code=502,
        ) from exc

    accumulated = response.choices[0].message.content or ""
    usage = response.usage
    citations = _citations_from_chunks(relevant_chunks)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=accumulated,
        input_tokens=usage.prompt_tokens if usage else 0,
        output_tokens=usage.completion_tokens if usage else 0,
        citations=citations,
    )
    db.add(assistant_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    await db.commit()
    return assistant_message
