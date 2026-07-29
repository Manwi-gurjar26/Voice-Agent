"""OpenAI client access for speech-to-text and text-to-speech (Step 7).

A single lazily-constructed client behind one function, so tests can
substitute a fake without network access or a real API key by monkeypatching
`get_openai_client` — never construct AsyncOpenAI() anywhere else in this
codebase, or that seam stops working. Mirrors app/services/llm.py.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from app.core.config import settings

_client: AsyncOpenAI | None = None


class VoiceUnavailableError(Exception):
    """Raised when voice is invoked but no OpenAI API key is configured."""


def get_openai_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise VoiceUnavailableError("OPENAI_API_KEY is not configured.")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _reset_client_for_tests() -> None:
    global _client
    _client = None


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe a recorded utterance to text via Whisper."""
    client = get_openai_client()
    transcription = await client.audio.transcriptions.create(
        model=settings.voice_stt_model,
        file=(filename, audio_bytes),
    )
    return transcription.text.strip()


async def synthesize_speech(text: str, voice: str | None) -> bytes:
    """Synthesize spoken audio (MP3 bytes) for a reply.

    `text` is truncated to 4096 chars — OpenAI TTS's own input cap — as a
    defensive measure; a reply this long would already be unusual given
    Agent.max_output_tokens.
    """
    client = get_openai_client()
    response = await client.audio.speech.create(
        model=settings.voice_tts_model,
        voice=voice or settings.voice_default_voice,
        input=text[:4096],
        response_format="mp3",
    )
    return await response.aread()
