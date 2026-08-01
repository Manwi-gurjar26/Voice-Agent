"""Local, free speech-to-text and text-to-speech (Step 7).

Originally OpenAI Whisper + tts-1; swapped to fully local, open-source
models because voice inherently needed a paid, metered API otherwise, and
this project's hosting account cannot take on any billing. faster-whisper
(a CTranslate2-based Whisper implementation) and Piper (a fast neural TTS
engine) both run entirely on CPU with zero network calls once their model
files are cached locally — the exact pattern already used for RAG
embeddings in app/services/embeddings.py (a local sentence-transformers
model instead of a hosted API), not a new architectural idea for this
codebase.

Two lazily-constructed, cached objects behind two functions
(get_whisper_model/get_piper_voice), mirroring the get_anthropic_client/
get_openai_client seam pattern elsewhere in this codebase — tests
monkeypatch these two functions rather than touching the real models.
Both real model calls are CPU-bound and synchronous, so both public
functions run them via asyncio.to_thread — calling either directly from an
async handler would block the event loop for every other in-flight request,
same reasoning as embeddings.py's embed_texts/embed_query.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path

from faster_whisper import WhisperModel
from piper import PiperVoice
from piper.download_voices import download_voice

from app.core.config import settings

_whisper_model: WhisperModel | None = None
_piper_voices: dict[str, PiperVoice] = {}


class VoiceUnavailableError(Exception):
    """Raised when a local model fails to load (e.g. no internet on a cold
    cache, or a corrupted download) — the local equivalent of the old
    "no API key configured" condition, structurally rarer since there is no
    external account/billing dependency anymore, but still a real failure
    mode worth a clean 503 rather than a raw exception."""


def get_whisper_model() -> WhisperModel:
    global _whisper_model
    if _whisper_model is None:
        try:
            _whisper_model = WhisperModel(
                settings.voice_stt_model_size, device="cpu", compute_type="int8"
            )
        except Exception as exc:
            raise VoiceUnavailableError(f"Could not load the local STT model: {exc}") from exc
    return _whisper_model


def get_piper_voice(voice_id: str) -> PiperVoice:
    if voice_id not in _piper_voices:
        try:
            voices_dir = Path(settings.voice_models_dir)
            voices_dir.mkdir(parents=True, exist_ok=True)
            model_path = voices_dir / f"{voice_id}.onnx"
            config_path = voices_dir / f"{voice_id}.onnx.json"
            if not model_path.exists() or not config_path.exists():
                download_voice(voice_id, voices_dir)
            _piper_voices[voice_id] = PiperVoice.load(str(model_path), config_path=str(config_path))
        except Exception as exc:
            raise VoiceUnavailableError(f"Could not load the local TTS voice: {exc}") from exc
    return _piper_voices[voice_id]


def _reset_client_for_tests() -> None:
    global _whisper_model
    _whisper_model = None
    _piper_voices.clear()


def _transcribe_sync(audio_bytes: bytes) -> str:
    model = get_whisper_model()
    # faster-whisper decodes via PyAV (bundled ffmpeg, no system dependency)
    # directly from a byte stream — format-agnostic, so the webm/opus the
    # widget records and the mp4/aac Safari falls back to both work without
    # needing to know which one this is, unlike OpenAI's API which used the
    # filename extension as a hint.
    segments, _info = model.transcribe(io.BytesIO(audio_bytes))
    return " ".join(segment.text for segment in segments).strip()


async def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe a recorded utterance to text via a local Whisper model."""
    return await asyncio.to_thread(_transcribe_sync, audio_bytes)


def _synthesize_sync(text: str, voice_id: str) -> bytes:
    voice = get_piper_voice(voice_id)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)
    return buf.getvalue()


async def synthesize_speech(text: str, voice: str | None) -> bytes:
    """Synthesize spoken audio (WAV bytes) for a reply via a local Piper voice.

    `text` is truncated defensively — a reply this long would already be
    unusual given Agent.max_output_tokens.
    """
    voice_id = voice or settings.voice_default_voice
    return await asyncio.to_thread(_synthesize_sync, text[:4096], voice_id)
