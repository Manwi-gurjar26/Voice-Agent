from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import voice

pytestmark = pytest.mark.skipif(
    not (settings.groq_api_key and settings.fish_audio_api_key),
    reason="needs real GROQ_API_KEY and FISH_AUDIO_API_KEY (network calls)",
)


async def test_synthesize_then_transcribe_round_trip_recovers_the_text():
    """The one real-model integration test for voice: proves the actual
    production path (Fish Audio TTS synth -> MP3 bytes -> Groq Whisper
    transcribe -> text) recovers text a person would recognize as correct,
    not just that the API calls succeed. test_voice.py fakes both calls for
    speed and deterministic control; this test is what justifies trusting
    those fakes reflect real behavior — mirrors test_embeddings.py's role
    for the RAG embedding model. Needs network access and both real API keys.
    """
    text = "What can you help me with today?"

    audio_bytes = await voice.synthesize_speech(text, settings.voice_default_voice)
    # A real MPEG audio frame (0xFF followed by a byte with its top 3 bits
    # set), not a stub — Fish Audio's s2.1-pro-free model returns raw MP3,
    # no container header to check the way WAV's "RIFF" magic worked before.
    assert audio_bytes[0] == 0xFF
    assert audio_bytes[1] & 0xE0 == 0xE0
    assert len(audio_bytes) > 1_000  # more than a couple of frames — real audio data

    transcript = await voice.transcribe_audio(audio_bytes, "reply.mp3")
    lowered = transcript.lower()
    for word in ("help", "today"):
        assert word in lowered, f"expected {word!r} in transcript {transcript!r}"
