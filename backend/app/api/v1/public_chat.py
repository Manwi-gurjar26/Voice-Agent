from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import DbSession
from app.api.public_deps import WidgetSessionDep, enforce_session_rate_limit
from app.schemas.chat import ConversationRead, MessageCreate, MessageListResponse, MessageRead
from app.services import chat as chat_service

router = APIRouter()

RateLimited = Annotated[None, Depends(enforce_session_rate_limit)]


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
