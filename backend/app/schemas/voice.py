from __future__ import annotations

from pydantic import BaseModel

from app.schemas.chat import MessageRead


class VoiceReplyResponse(BaseModel):
    transcript: str
    message: MessageRead
    audio_base64: str
    audio_mime: str = "audio/wav"
