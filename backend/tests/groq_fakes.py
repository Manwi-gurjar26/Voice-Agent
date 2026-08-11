"""Shared fake Groq client.

Lives in its own module because both test_chat.py (the Gemini->Groq
fallback) and test_voice.py need it, and those two already import from
each other — importing it from either one would be a cycle.
"""

from __future__ import annotations

from app.services import groq_llm


class _FakeGroqMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeGroqChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeGroqMessage(content)


class _FakeGroqUsage:
    def __init__(self, prompt_tokens: int = 42, completion_tokens: int = 7) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeGroqResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeGroqChoice(content)]
        self.usage = _FakeGroqUsage()


class _FakeGroqDelta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeGroqStreamChoice:
    def __init__(self, content: str | None, finish_reason: str | None) -> None:
        self.delta = _FakeGroqDelta(content)
        self.finish_reason = finish_reason


class _FakeGroqStreamChunk:
    def __init__(self, content: str | None, finish_reason: str | None = None) -> None:
        self.choices = [_FakeGroqStreamChoice(content, finish_reason)]
        self.usage = None


class _FakeGroqUsageChunk:
    """Groq sends usage in a final chunk that carries no choices."""

    def __init__(self) -> None:
        self.choices = []
        self.usage = _FakeGroqUsage()


async def _fake_groq_stream(
    chunks: tuple[str, ...], delay_seconds: float, error: Exception | None
):
    import asyncio

    for i, chunk in enumerate(chunks):
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
        last = i == len(chunks) - 1
        yield _FakeGroqStreamChunk(chunk, finish_reason="stop" if last else None)
    if error is not None:
        raise error
    yield _FakeGroqUsageChunk()


class _FakeGroqCompletions:
    def __init__(
        self,
        chunks: tuple[str, ...],
        delay_seconds: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self._chunks = chunks
        self._delay_seconds = delay_seconds
        self._error = error
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            # An error with no chunks must surface from create() itself, the
            # way a rejected request does, not from iterating the stream.
            if self._error is not None and not self._chunks:
                raise self._error
            return _fake_groq_stream(self._chunks, self._delay_seconds, self._error)
        if self._error is not None:
            raise self._error
        return _FakeGroqResponse("".join(self._chunks))


class _FakeGroqChat:
    def __init__(self, completions: _FakeGroqCompletions) -> None:
        self.completions = completions


class FakeGroqClient:
    def __init__(self, completions: _FakeGroqCompletions) -> None:
        self.chat = _FakeGroqChat(completions)

    @property
    def last_kwargs(self) -> dict | None:
        return self.chat.completions.last_kwargs


def install_fake_groq_client(
    monkeypatch, reply: str | Exception = "We're open 9 to 5."
) -> FakeGroqClient:
    """Patch app.services.groq_llm.get_groq_client for the duration of a test.

    `reply` keeps the original string-or-Exception shape used by the voice
    tests; install_fake_chat_client below is the streaming-oriented form.
    """
    if isinstance(reply, Exception):
        return install_fake_chat_client(monkeypatch, chunks=(), error=reply)
    return install_fake_chat_client(monkeypatch, chunks=(reply,))


def install_fake_chat_client(
    monkeypatch,
    chunks: tuple[str, ...] = ("Hello", ", ", "world!"),
    delay_seconds: float = 0.0,
    error: Exception | None = None,
) -> FakeGroqClient:
    """Fake the provider that typed chat actually uses. Mirrors the shape of
    test_chat's former Gemini fake so provider-agnostic tests read the same."""
    fake_client = FakeGroqClient(
        _FakeGroqCompletions(chunks, delay_seconds=delay_seconds, error=error)
    )
    monkeypatch.setattr(groq_llm, "get_groq_client", lambda: fake_client)
    return fake_client
