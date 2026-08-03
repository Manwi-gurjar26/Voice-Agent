from __future__ import annotations

import base64
from types import SimpleNamespace

from app.core.config import settings
from app.services import voice
from tests.test_auth import register
from tests.test_chat import install_fake_client, make_widget_session, session_auth
from tests.test_public import make_active_agent

PREFIX = settings.api_v1_prefix

AUDIO_BYTES = b"pretend-this-is-a-webm-audio-clip"


# --------------------------------------------------------------------------
# Fake local models — the seams are get_whisper_model/get_piper_voice,
# mirroring test_chat.py's install_fake_client for the Gemini seam.
# Real model behavior (that synthesized audio actually transcribes back to
# recognizable text) is covered separately in test_voice_models.py.
# --------------------------------------------------------------------------
class FakeWhisperModel:
    def __init__(self, result: str | Exception) -> None:
        self._result = result
        self.last_audio = None

    def transcribe(self, audio, **kwargs):
        self.last_audio = audio
        if isinstance(self._result, Exception):
            raise self._result
        segments = [SimpleNamespace(text=self._result)] if self._result.strip() else []
        return segments, SimpleNamespace(language="en", language_probability=1.0)


class FakePiperVoice:
    def __init__(self, fail: Exception | None = None) -> None:
        self._fail = fail
        self.last_text: str | None = None

    def synthesize_wav(self, text, wav_file) -> None:
        self.last_text = text
        if self._fail:
            raise self._fail
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)


def install_fake_voice_client(
    monkeypatch,
    transcript: str | Exception = "What are your hours?",
    tts_fail: Exception | None = None,
) -> tuple[FakeWhisperModel, FakePiperVoice]:
    fake_model = FakeWhisperModel(transcript)
    fake_voice = FakePiperVoice(fail=tts_fail)
    monkeypatch.setattr(voice, "get_whisper_model", lambda: fake_model)
    monkeypatch.setattr(voice, "get_piper_voice", lambda voice_id: fake_voice)
    return fake_model, fake_voice


async def make_voice_conversation(client, session) -> str:
    conv = (
        await client.post(f"{PREFIX}/public/conversations", headers=session_auth(session))
    ).json()
    return conv["id"]


def post_voice_message(client, conversation_id, session, audio: bytes = AUDIO_BYTES):
    return client.post(
        f"{PREFIX}/public/conversations/{conversation_id}/voice-messages",
        headers=session_auth(session),
        files={"file": ("clip.webm", audio, "audio/webm")},
    )


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------
async def test_voice_message_happy_path(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript="What are your hours?")
    install_fake_client(monkeypatch, chunks=("We're open 9 to 5.",))

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "What are your hours?"
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "We're open 9 to 5."
    assert body["audio_mime"] == "audio/wav"
    # A real WAV file (the fake still runs the real wave-writing code in
    # voice.py's _synthesize_sync — only get_piper_voice itself is faked).
    assert base64.b64decode(body["audio_base64"])[:4] == b"RIFF"


async def test_voice_message_persists_both_turns(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Message

    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript="hello")
    install_fake_client(monkeypatch, chunks=("hi there",))

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)
    assert response.status_code == 200, response.text

    rows = list(await db_session.scalars(select(Message).order_by(Message.created_at)))
    assert [r.role for r in rows] == ["user", "assistant"]
    assert rows[0].content == "hello"
    assert rows[1].content == "hi there"


# --------------------------------------------------------------------------
# Error branches
# --------------------------------------------------------------------------
async def test_voice_disabled_agent_is_rejected(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens)  # voice_enabled defaults False
    install_fake_voice_client(monkeypatch)

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "voice_not_enabled"


async def test_oversized_recording_is_rejected(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch)
    monkeypatch.setattr(settings, "max_voice_upload_bytes", 10)

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session, audio=b"x" * 11)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


async def test_empty_transcript_is_rejected(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript="   ")

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_transcript"


async def test_transcription_failure_maps_to_a_clean_error(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript=RuntimeError("decoder crashed"))

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "transcription_failed"


async def test_llm_failure_after_transcription_maps_to_a_clean_error(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript="hello")
    install_fake_client(monkeypatch, chunks=(), error=RuntimeError("claude is down"))

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "llm_error"


async def test_tts_failure_still_returns_the_text_reply(client, monkeypatch, db_session):
    """Speech synthesis failing after a successful chat reply degrades to a
    silent (no-audio) response rather than discarding the reply — see the
    endpoint's docstring comment."""
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(
        monkeypatch, transcript="hello", tts_fail=RuntimeError("synth crashed")
    )
    install_fake_client(monkeypatch, chunks=("hi there",))

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"]["content"] == "hi there"
    assert body["audio_base64"] == ""


async def test_quota_exceeded_is_rejected_before_any_provider_call(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Tenant

    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch)
    install_fake_client(monkeypatch, chunks=("should not be reached",))

    tenant = await db_session.scalar(select(Tenant))
    tenant.monthly_message_quota = 0
    await db_session.commit()

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 402
    assert response.json()["error"]["code"] == "quota_exceeded"


async def test_missing_session_token_is_rejected(client, monkeypatch, db_session):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch)

    from tests.test_public import ORIGIN

    response = await client.post(
        f"{PREFIX}/public/conversations/00000000-0000-0000-0000-000000000000/voice-messages",
        headers={"Origin": ORIGIN},
        files={"file": ("clip.webm", AUDIO_BYTES, "audio/webm")},
    )
    assert response.status_code == 401
    assert agent["voice_enabled"] is True


async def test_wrong_origin_is_rejected(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch)

    conv_id = await make_voice_conversation(client, session)
    response = await client.post(
        f"{PREFIX}/public/conversations/{conv_id}/voice-messages",
        headers={
            "Authorization": f"Bearer {session['session_token']}",
            "Origin": "https://evil.example.com",
        },
        files={"file": ("clip.webm", AUDIO_BYTES, "audio/webm")},
    )
    assert response.status_code == 403


async def test_unknown_conversation_id_is_404(client, monkeypatch, db_session):
    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch)

    response = await post_voice_message(
        client, "00000000-0000-0000-0000-000000000000", session
    )
    assert response.status_code == 404


async def test_voice_unavailable_when_model_fails_to_load(client, monkeypatch, db_session):
    """No API key exists to unset anymore — the local equivalent of "voice
    unavailable" is a model failing to load (e.g. no internet on a cold
    cache). Simulated directly at the seam rather than actually breaking
    network access, which the real get_whisper_model already translates
    into VoiceUnavailableError (see its except clause)."""

    def _raise():
        raise voice.VoiceUnavailableError("model unavailable")

    monkeypatch.setattr(voice, "get_whisper_model", _raise)

    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "voice_unavailable"


# --------------------------------------------------------------------------
# CORS preflight
# --------------------------------------------------------------------------
async def test_preflight_for_voice_messages_route_reflects_origin(client):
    response = await client.options(
        f"{PREFIX}/public/conversations/00000000-0000-0000-0000-000000000000/voice-messages",
        headers={
            "Origin": "https://anything.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "https://anything.example.com"
