"""Conversation creation, message persistence, and the Claude streaming turn."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, QuotaExceededError
from app.models import Agent, Chunk, Conversation, Message
from app.models.widget_session import WidgetSession
from app.services import embeddings, llm
from app.services.quota import check_and_consume_quota
from app.services.retrieval import agent_has_chunks, find_relevant_chunks

logger = logging.getLogger(__name__)

# Defensive cap on how much history we load and resend to Claude per turn —
# not a product-facing pagination limit. A conversation this long is already
# unusual; this exists so one doesn't grow the request payload unboundedly.
MAX_HISTORY_MESSAGES = 500


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


def _build_claude_messages(history: list[Message]) -> list[dict]:
    """Collapse consecutive same-role rows into alternating API turns.

    Rows are normally already alternating — one user message triggers exactly
    one persisted assistant reply — but if a prior turn's Claude call failed
    after the user message was saved (see stream_turn), the next user message
    lands right after another user row. Claude's API rejects non-alternating
    roles outright, so this merges runs of the same role into a single turn
    rather than 400ing on the very next message after any failure.
    """
    turns: list[dict] = []
    for row in history:
        if turns and turns[-1]["role"] == row.role:
            turns[-1]["content"] += f"\n\n{row.content}"
        else:
            turns.append({"role": row.role, "content": row.content})
    return turns


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


async def stream_turn(
    db: AsyncSession, conversation: Conversation, agent: Agent, user_content: str
) -> AsyncIterator[str]:
    """Persist the user message, enforce quota, call Claude, and stream SSE.

    Yields SSE-formatted (`event: ...\\ndata: ...\\n\\n`) chunks — pass this
    directly to `StreamingResponse(..., media_type="text/event-stream")`.

    Quota is consumed *before* calling Claude, unconditionally, with no
    refund if the call then fails. That's a deliberate cost-control choice,
    not an oversight: origin allowlisting (Step 3) can't stop a scripted
    client with a valid public_key from forging requests, so the quota
    counter needs to reflect attempted usage, not just successful usage, or
    a client could bypass it by triggering (and abandoning) failing calls.
    """
    try:
        await check_and_consume_quota(db, conversation.tenant_id)
    except QuotaExceededError as exc:
        await db.rollback()
        yield _sse("error", {"code": exc.code, "message": exc.message})
        return

    user_message = Message(conversation_id=conversation.id, role="user", content=user_content)
    db.add(user_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    # Commit now, not just at end-of-request: the user's message and their
    # quota consumption must survive even if the Claude call below fails.
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
    claude_messages = _build_claude_messages(history)

    accumulated = ""
    try:
        client = llm.get_anthropic_client()
        async with client.messages.stream(
            model=agent.model,
            max_tokens=agent.max_output_tokens,
            system=system_prompt,
            messages=claude_messages,
            output_config={"effort": agent.effort},
        ) as stream:
            async for text in stream.text_stream:
                accumulated += text
                yield _sse("delta", {"text": text})
            final = await stream.get_final_message()
    except Exception:
        logger.exception("Claude call failed for conversation %s", conversation.id)
        yield _sse(
            "error",
            {
                "code": "llm_error",
                "message": "The assistant is temporarily unavailable. Please try again.",
            },
        )
        return

    citations = _citations_from_chunks(relevant_chunks)
    assistant_message = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=accumulated,
        input_tokens=final.usage.input_tokens,
        output_tokens=final.usage.output_tokens,
        citations=citations,
    )
    db.add(assistant_message)
    conversation.last_message_at = datetime.now(timezone.utc)
    await db.commit()

    yield _sse(
        "done",
        {
            "message_id": str(assistant_message.id),
            "stop_reason": final.stop_reason,
            "usage": {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            },
            "citations": citations or [],
        },
    )
