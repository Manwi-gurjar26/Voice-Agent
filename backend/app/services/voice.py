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

import re

import httpx

from app.core.config import settings
from app.services.groq_llm import get_groq_client

_STT_MODEL = "whisper-large-v3-turbo"
_TTS_MODEL = "s2.1-pro-free"
_TTS_URL = "https://api.fish.audio/v1/tts"

# Fish Audio speaks markdown punctuation out loud and garbles the words around
# it — confirmed by synthesizing a formatted reply and transcribing the audio
# back: "used to **manage state**" was spoken as "used to asterisk asterisk
# manage state asterisk asterisk manage state", repeating the phrase. The
# voice prompt already asks the model for plain prose (see chat.py's
# _VOICE_BREVITY_INSTRUCTION), but the model doesn't always comply, so the
# text is flattened here before it can reach the synthesizer.
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LIST_BULLET = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]*", re.MULTILINE)
_BLOCKQUOTE = re.compile(r"^[ \t]*>[ \t]?", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3})")
_TABLE_PIPE = re.compile(r"[ \t]*\|[ \t]*")
# Pictographs, symbols, flags, dingbats — spoken aloud as their CLDR name
# ("house building") in the middle of a sentence.
_EMOJI = re.compile(
    "[\U0001f000-\U0001faff\U00002190-\U000021ff\U00002300-\U000027bf\U00002b00-\U00002bff️]"
)


def to_speakable_text(text: str) -> str:
    """Flatten a written reply into something a TTS engine reads cleanly.

    List items become their own sentences rather than running together, so
    the synthesized speech still pauses where the bullets were.
    """
    cleaned = _FENCED_CODE.sub(" ", text)
    cleaned = _IMAGE.sub(r"\1", cleaned)
    cleaned = _LINK.sub(r"\1", cleaned)
    cleaned = _HEADING.sub("", cleaned)
    cleaned = _BLOCKQUOTE.sub("", cleaned)
    cleaned = _TABLE_PIPE.sub(", ", cleaned)

    # Give each bullet a sentence ending before the marker disappears,
    # otherwise "…reducer function It returns…" runs on as one breath.
    lines = []
    for line in _LIST_BULLET.sub("", cleaned).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[-1] not in ".!?,:;":
            stripped += "."
        lines.append(stripped)
    cleaned = " ".join(lines)

    cleaned = cleaned.replace("`", "")
    cleaned = _EMPHASIS.sub("", cleaned)
    cleaned = _EMOJI.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Never hand back an empty string (a reply that was nothing but a code
    # block) — the caller would synthesize silence.
    return cleaned or text.strip()


class VoiceUnavailableError(Exception):
    """Raised when Groq's STT or Fish Audio's TTS can't be reached."""


async def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    """Transcribe a recorded utterance to text via Groq's hosted Whisper."""
    client = get_groq_client()
    try:
        response = await client.audio.transcriptions.create(
            model=_STT_MODEL,
            file=(filename, audio_bytes),
            # Told, not guessed: auto-detection on a short, accented clip can
            # land on the wrong language, and the reply then follows the
            # transcript into a language the visitor never spoke.
            language=settings.voice_language,
        )
    except Exception as exc:
        raise VoiceUnavailableError(f"Could not reach Groq's speech-to-text: {exc}") from exc
    return (response.text or "").strip()


async def synthesize_speech(text: str, voice: str | None) -> bytes:
    """Synthesize spoken audio (MP3 bytes) for a reply via Fish Audio's free
    s2.1-pro-free model. `voice`, when set, is passed through as a Fish
    Audio `reference_id` (a voice clone/preset from that account's library);
    the account's default voice is used otherwise.

    `text` is truncated defensively to roughly what chat_service's voice
    path already asks the model to stay within (a few short spoken
    sentences) — confirmed live that this free tier synthesizes at
    ~20ms/char, so an untruncated text-chat-length reply (thousands of
    chars) can take a minute or more to speak.
    """
    payload: dict = {"text": to_speakable_text(text)[:600]}
    # Falling through to no reference_id at all is what let the speaker (and
    # apparent language) change between replies — see voice_default_voice.
    reference_id = voice or settings.voice_default_voice
    if reference_id:
        payload["reference_id"] = reference_id
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
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
