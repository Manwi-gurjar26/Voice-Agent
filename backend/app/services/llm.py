"""Gemini client access.

A single lazily-constructed client behind one function, so tests can
substitute a fake without network access or a real API key by monkeypatching
`get_gemini_client` — never construct genai.Client() anywhere else in this
codebase, or that seam stops working.

Originally Anthropic (Claude); swapped to Google Gemini because Claude has
no perpetual free tier and this project cannot take on any paid API cost.
Gemini's free tier (via Google AI Studio) needs only a Google account, no
card — see README's chat-pipeline section for the full rationale.
"""

from __future__ import annotations

from google import genai

from app.core.config import settings

_client: genai.Client | None = None


def get_gemini_client() -> genai.Client:
    global _client
    if _client is None:
        # genai.Client raises ValueError immediately if api_key is None/empty
        # — unlike AsyncAnthropic, which only fails on the first real request.
        # Both land in the same place: chat.py's broad except around the
        # call site turns either into a clean "llm_error" SSE event.
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _reset_client_for_tests() -> None:
    global _client
    _client = None
