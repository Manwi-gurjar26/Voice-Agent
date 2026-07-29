"""Anthropic client access.

A single lazily-constructed client behind one function, so tests can
substitute a fake without network access or a real API key by monkeypatching
`get_anthropic_client` — never construct AsyncAnthropic() anywhere else in
this codebase, or that seam stops working.
"""

from __future__ import annotations

from anthropic import AsyncAnthropic

from app.core.config import settings

_client: AsyncAnthropic | None = None


def get_anthropic_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _reset_client_for_tests() -> None:
    global _client
    _client = None
