"""Groq client access — used for voice's STT and LLM steps only (see
app/services/voice.py and chat.py's complete_turn). Typed chat stays on
Gemini (app/services/llm.py); this seam exists specifically because voice
replies were asked to run on Groq's llama-3.1-8b-instant instead. Groq's
free tier needs only an email, no card.
"""

from __future__ import annotations

from groq import AsyncGroq

from app.core.config import settings

_client: AsyncGroq | None = None


def get_groq_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=settings.groq_api_key)
    return _client


def _reset_client_for_tests() -> None:
    global _client
    _client = None
