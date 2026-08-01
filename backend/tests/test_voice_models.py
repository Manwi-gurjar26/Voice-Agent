from __future__ import annotations

from app.services import voice


async def test_synthesize_then_transcribe_round_trip_recovers_the_text():
    """The one real-model integration test for voice: proves the actual
    production path (Piper synth -> WAV bytes -> faster-whisper decode ->
    text) recovers text a person would recognize as correct, not just that
    both libraries import successfully. test_voice.py fakes both models for
    speed and deterministic control; this test is what justifies trusting
    those fakes reflect real behavior — mirrors test_embeddings.py's role
    for the RAG embedding model.
    """
    text = "What can you help me with today?"

    audio_bytes = await voice.synthesize_speech(text, "en_US-lessac-medium")
    assert audio_bytes[:4] == b"RIFF"  # a real WAV file, not a stub
    assert len(audio_bytes) > 1_000  # more than just a header — real audio data

    transcript = await voice.transcribe_audio(audio_bytes)
    lowered = transcript.lower()
    for word in ("help", "today"):
        assert word in lowered, f"expected {word!r} in transcript {transcript!r}"
