from __future__ import annotations

import base64
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response, StreamingResponse

from app.api.deps import DbSession
from app.api.public_deps import WidgetSessionDep, enforce_session_rate_limit
from app.core.config import settings
from app.core.errors import AppError
from app.schemas.chat import ConversationRead, MessageCreate, MessageListResponse, MessageRead
from app.schemas.voice import VoiceReplyResponse
from app.services import chat as chat_service
from app.services import voice as voice_service

logger = logging.getLogger(__name__)

router = APIRouter()

RateLimited = Annotated[None, Depends(enforce_session_rate_limit)]

_PREFLIGHT_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Max-Age": "600",
}


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=201,
    summary="Start a new conversation for the current widget session",
)
async def create_conversation(
    session: WidgetSessionDep, _rl: RateLimited, db: DbSession
) -> ConversationRead:
    conversation = await chat_service.create_conversation(db, session)
    return ConversationRead.model_validate(conversation)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="Fetch a conversation's message history",
)
async def list_messages(
    conversation_id: uuid.UUID, session: WidgetSessionDep, _rl: RateLimited, db: DbSession
) -> MessageListResponse:
    conversation = await chat_service.get_owned_conversation(db, session, conversation_id)
    messages = await chat_service.list_messages(db, conversation)
    return MessageListResponse(items=[MessageRead.model_validate(m) for m in messages])


@router.post(
    "/conversations/{conversation_id}/messages",
    summary="Send a message and stream the assistant's reply",
)
async def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    session: WidgetSessionDep,
    _rl: RateLimited,
    db: DbSession,
) -> StreamingResponse:
    # get_owned_conversation runs (and can 404) before any bytes are written,
    # so an unauthorized conversation_id never gets a 200-with-SSE-error —
    # it gets the normal 404 JSON error every other route in this app uses.
    conversation = await chat_service.get_owned_conversation(db, session, conversation_id)
    return StreamingResponse(
        chat_service.stream_turn(db, conversation, session.agent, payload.content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Hints a fronting reverse proxy (e.g. nginx) not to buffer the
            # stream — irrelevant locally, load-bearing once this sits behind
            # one in Step 10.
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/conversations/{conversation_id}/voice-messages",
    response_model=VoiceReplyResponse,
    summary="Send a spoken message and get a spoken reply (Step 7)",
)
async def send_voice_message(
    conversation_id: uuid.UUID,
    session: WidgetSessionDep,
    _rl: RateLimited,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> VoiceReplyResponse:
    # Checked here too, not just by the widget hiding its mic button — a
    # scripted client could otherwise hit this route for an agent that never
    # opted into voice.
    if not session.agent.voice_enabled:
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

    # Same ownership check as the text route — 404s before any provider call
    # or quota consumption happens for a conversation_id this session doesn't own.
    conversation = await chat_service.get_owned_conversation(db, session, conversation_id)

    try:
        transcript = await voice_service.transcribe_audio(content)
    except voice_service.VoiceUnavailableError as exc:
        raise AppError(
            str(exc), code="voice_unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc
    except Exception as exc:
        logger.exception("Transcription failed for conversation %s", conversation_id)
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

    assistant_message = await chat_service.complete_turn(db, conversation, session.agent, transcript)

    # The text reply is already safely persisted at this point (it's also
    # visible on the next listMessages fetch regardless) — a TTS failure
    # degrades to a silent reply rather than discarding a reply that
    # succeeded, instead of raising and losing it from the response entirely.
    try:
        audio_bytes = await voice_service.synthesize_speech(
            assistant_message.content, session.agent.voice_id
        )
        audio_base64 = base64.b64encode(audio_bytes).decode("ascii")
    except Exception:
        logger.exception("Speech synthesis failed for conversation %s", conversation_id)
        audio_base64 = ""

    return VoiceReplyResponse(
        transcript=transcript,
        message=MessageRead.model_validate(assistant_message),
        audio_base64=audio_base64,
    )


# --------------------------------------------------------------------------
# CORS preflight
#
# None of these routes have {public_key} in their path (see public.py's
# /sessions/me for the same situation), so preflight can't check the origin
# allowlist before the real request runs — a browser's preflight OPTIONS
# carries no Authorization header. Enforcement is the bearer token plus the
# origin re-check inside WidgetSessionDep, on the real request; this just
# lets the preflight itself succeed so the browser sends that real request.
# --------------------------------------------------------------------------
@router.options("/conversations", include_in_schema=False)
@router.options("/conversations/{conversation_id}/messages", include_in_schema=False)
@router.options("/conversations/{conversation_id}/voice-messages", include_in_schema=False)
async def preflight_for_conversation_routes() -> Response:
    return Response(status_code=204, headers=_PREFLIGHT_HEADERS)
