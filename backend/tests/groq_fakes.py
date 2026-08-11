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
    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
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
    def __init__(self, content: str | None) -> None:
        self.delta = _FakeGroqDelta(content)


class _FakeGroqStreamChunk:
    def __init__(self, content: str | None) -> None:
        self.choices = [_FakeGroqStreamChoice(content)]


async def _fake_groq_stream(reply: str):
    """Word-by-word, so a caller that accumulates deltas is actually
    exercised rather than handed the whole reply in one chunk."""
    for word in reply.split(" "):
        yield _FakeGroqStreamChunk(word + " ")


class _FakeGroqCompletions:
    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        if isinstance(self._reply, Exception):
            raise self._reply
        if kwargs.get("stream"):
            return _fake_groq_stream(self._reply)
        return _FakeGroqResponse(self._reply)


class _FakeGroqChat:
    def __init__(self, completions: _FakeGroqCompletions) -> None:
        self.completions = completions


class FakeGroqClient:
    def __init__(self, reply: str | Exception) -> None:
        self.chat = _FakeGroqChat(_FakeGroqCompletions(reply))


def install_fake_groq_client(monkeypatch, reply: str | Exception = "We're open 9 to 5.") -> FakeGroqClient:
    """Patch app.services.groq_llm.get_groq_client for the duration of a
    test. Returns the fake client so tests can inspect what was requested."""
    fake_client = FakeGroqClient(reply)
    monkeypatch.setattr(groq_llm, "get_groq_client", lambda: fake_client)
    return fake_client
