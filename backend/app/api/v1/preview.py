"""Dashboard-authenticated preview of an agent.

The widget's own endpoints (app/api/v1/public_chat.py) authorise a caller by
Origin allowlist plus a widget session token, and refuse any agent that is not
`active`. Both rules are correct there and both make that path unusable as a
dashboard preview: the dashboard's own origin is not on any customer's
allowlist, and the agent you most want to try before shipping is precisely the
one still in `draft`.

So this is a parallel entry point rather than a relaxation of that one — the
public path keeps its invariants untouched. Here the authorisation boundary is
the normal dashboard one: a signed-in user, and an agent that belongs to their
tenant. Everything downstream (retrieval, quota, the LLM call, persistence)
runs through the same app/services/chat.py functions the real widget uses, so
a preview exercises the actual code path and not a mock of it.

Preview turns are ordinary rows: they consume quota, cost the same provider
call, and appear in analytics. Their widget session is tagged with the
PREVIEW_ORIGIN marker below so they are identifiable as internal testing
rather than traffic from a customer's site.
"""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import DbSession, TenantId, client_ip
from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.models import Conversation
from app.schemas.chat import ConversationRead, MessageCreate, MessageListResponse, MessageRead
from app.schemas.public import AgentPublicConfig
from app.schemas.voice import VoiceReplyResponse
from app.services import agents as agent_service
from app.services import chat as chat_service
from app.services import voice as voice_service
from app.services import widget_sessions as session_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Recorded as WidgetSession.origin for every preview session. A scheme that no
# browser can ever send, so it cannot collide with a real customer origin.
PREVIEW_ORIGIN = "preview://dashboard"


async def _owned_conversation(
    db: DbSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    """Scoped to tenant *and* agent, not to a widget session.

    The widget scopes conversations to one browser session so two visitors on
    the same site cannot read each other's threads. That is the wrong boundary
    here: the caller owns the agent, and the point of the preview is to reopen
    a thread you started a minute ago from a page that has since reloaded.
    404 rather than 403, matching every other ownership check in this app.
    """
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.agent_id == agent_id,
        )
    )
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


@router.get(
    "/{agent_id}/preview/config",
    response_model=AgentPublicConfig,
    summary="What the widget would render for this agent",
)
async def preview_config(
    agent_id: uuid.UUID, db: DbSession, tenant_id: TenantId
) -> AgentPublicConfig:
    """Deliberately the same schema the real widget bootstraps from, so the
    preview cannot drift into showing fields a visitor would never see."""
    agent = await agent_service.get_agent(db, tenant_id, agent_id)
    return AgentPublicConfig.model_validate(agent)


@router.post(
    "/{agent_id}/preview/conversations",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start a preview conversation",
)
async def start_preview_conversation(
    agent_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantId,
    request: Request,
    ip: Annotated[str | None, Depends(client_ip)],
) -> ConversationRead:
    agent = await agent_service.get_agent(db, tenant_id, agent_id)

    # A Conversation requires a widget_session_id (NOT NULL), and writing one
    # real session row per preview thread keeps the schema honest — no
    # nullable column added, and no second kind of conversation for every
    # later query to know about.
    session = await session_service.new_widget_session(
        db,
        agent,
        origin=PREVIEW_ORIGIN,
        user_agent=request.headers.get("User-Agent"),
        ip_address=ip,
    )
    conversation = await chat_service.create_conversation(db, session)
    return ConversationRead.model_validate(conversation)


@router.get(
    "/{agent_id}/preview/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="Preview conversation history",
)
async def list_preview_messages(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantId,
) -> MessageListResponse:
    conversation = await _owned_conversation(db, tenant_id, agent_id, conversation_id)
    messages = await chat_service.list_messages(db, conversation)
    return MessageListResponse(items=[MessageRead.model_validate(m) for m in messages])


@router.post(
    "/{agent_id}/preview/conversations/{conversation_id}/messages",
    summary="Send a preview message and stream the reply",
)
async def send_preview_message(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    db: DbSession,
    tenant_id: TenantId,
) -> StreamingResponse:
    agent = await agent_service.get_agent(db, tenant_id, agent_id)
    # Resolved (and able to 404) before a single byte of the stream is
    # written, so an unowned id gets the normal JSON error rather than a
    # 200 carrying an error event.
    conversation = await _owned_conversation(db, tenant_id, agent_id, conversation_id)
    return StreamingResponse(
        chat_service.stream_turn(db, conversation, agent, payload.content),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/{agent_id}/preview/conversations/{conversation_id}/voice-messages",
    response_model=VoiceReplyResponse,
    summary="Send a spoken preview message and get a spoken reply",
)
async def send_preview_voice_message(
    agent_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: DbSession,
    tenant_id: TenantId,
    file: Annotated[UploadFile, File()],
) -> VoiceReplyResponse:
    agent = await agent_service.get_agent(db, tenant_id, agent_id)
    if not agent.voice_enabled:
        raise AppError(
            "Voice is not enabled for this agent.",
            code="voice_not_enabled",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    content = await file.read()
    if len(content) > settings.max_voice_upload_bytes:
        limit_mb = settings.max_voice_upload_bytes // (1024 * 1024)
        raise AppError(
            f"Recording exceeds the {limit_mb}MB limit.",
            code="file_too_large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )

    conversation = await _owned_conversation(db, tenant_id, agent_id, conversation_id)

    try:
        transcript = await voice_service.transcribe_audio(content, file.filename or "recording.webm")
    except voice_service.VoiceUnavailableError as exc:
        raise AppError(
            str(exc), code="voice_unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc
    except Exception as exc:
        logger.exception("Preview transcription failed for conversation %s", conversation_id)
        raise AppError(
            "Could not transcribe that recording. Please try again.",
            code="transcription_failed",
            status_code=status.HTTP_502_BAD_GATEWAY,
        ) from exc

    if not transcript:
        raise AppError(
            "Could not hear anything in that recording.",
            code="empty_transcript",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    assistant_message = await chat_service.complete_turn(db, conversation, agent, transcript)

    # Same degradation as the public voice route: the reply text is already
    # persisted, so a TTS failure yields a silent reply rather than throwing
    # away an answer that succeeded.
    try:
        audio_bytes = await voice_service.synthesize_speech(
            assistant_message.content, agent.voice_id
        )
        audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    except Exception:
        logger.exception("Preview speech synthesis failed for conversation %s", conversation_id)
        audio_base64 = ""

    return VoiceReplyResponse(
        transcript=transcript,
        message=MessageRead.model_validate(assistant_message),
        audio_base64=audio_base64,
    )


