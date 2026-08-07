"""Speech-to-text and text-to-speech (Step 7, v4).

STT: Groq's hosted Whisper (whisper-large-v3-turbo) — fast, and (like the
original OpenAI-based version) decodes whatever the browser recorded
directly from raw bytes, no local decoding step needed. The upload's real
filename is passed through as a format hint, same reasoning as the
original OpenAI version.

TTS: Fish Audio's `s2.1-pro-free` model. Confirmed directly against the
real API before wiring this in: Fish Audio's paid voices 402 with
"Insufficient API credit" on an account with zero balance, but the
`s2.1-pro-free` model works with that exact same zero balance and doesn't
deduct anything — it's a genuinely free tier, not a trial credit. The model
is selected via a `model` HTTP header, not a JSON body field — the body-field
form still routes to the paid tier and 402s.

Both of these are used only for *voice* replies — typed chat still runs on
Gemini (see chat_service.stream_turn / app/services/llm.py). This is the
third voice-provider swap in this project's history (OpenAI -> local
Whisper+Piper -> Gemini Live+TTS -> this) — see git history/README for why
each swap happened; this one is an explicit request to pipeline
best-of-breed free services rather than one bundled provider.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.groq_llm import get_groq_client

_STT_MODEL = "whisper-large-v3-turbo"
_TTS_MODEL = "s2.1-pro-free"
_TTS_URL = "https://api.fish.audio/v1/tts"


class VoiceUnavailableError(Exception):
    """Raised when Groq's STT or Fish Audio's TTS can't be reached."""


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe a recorded utterance to text via Groq's hosted Whisper."""
    client = get_groq_client()
    try:
        response = await client.audio.transcriptions.create(
            model=_STT_MODEL,
            file=(filename, audio_bytes),
        )
    except Exception as exc:
        raise VoiceUnavailableError(f"Could not reach Groq's speech-to-text: {exc}") from exc
    return (response.text or "").strip()


async def synthesize_speech(text: str, voice: str | None) -> bytes:
    """Synthesize spoken audio (MP3 bytes) for a reply via Fish Audio's free
    s2.1-pro-free model. `voice`, when set, is passed through as a Fish
    Audio `reference_id` (a voice clone/preset from that account's library);
    the account's default voice is used otherwise.

    `text` is truncated defensively — a reply this long would already be
    unusual given Agent.max_output_tokens.
    """
    payload: dict = {"text": text[:4096]}
    if voice:
        payload["reference_id"] = voice
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                _TTS_URL,
                headers={
                    "Authorization": f"Bearer {settings.fish_audio_api_key}",
                    "Content-Type": "application/json",
                    "model": _TTS_MODEL,
                },
                json=payload,
            )
            response.raise_for_status()
            return response.content
    except Exception as exc:
        raise VoiceUnavailableError(f"Could not reach Fish Audio's text-to-speech: {exc}") from exc
