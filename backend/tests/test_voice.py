from __future__ import annotations

import base64

from app.core.config import settings
from app.services import voice
from tests.test_auth import register
from tests.test_chat import install_fake_client, make_widget_session, session_auth
from tests.test_public import make_active_agent

PREFIX = settings.api_v1_prefix

AUDIO_BYTES = b"pretend-this-is-a-webm-audio-clip"


# --------------------------------------------------------------------------
# Fake OpenAI client — the seam is app.services.voice.get_openai_client,
# mirrors test_chat.py's install_fake_client for the Anthropic seam.
# --------------------------------------------------------------------------
class _FakeTranscription:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAudioResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def aread(self) -> bytes:
        return self._data


class _FakeTranscriptions:
    def __init__(self, result: str | Exception) -> None:
        self._result = result
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs) -> _FakeTranscription:
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return _FakeTranscription(self._result)


class _FakeSpeech:
    def __init__(self, result: bytes | Exception) -> None:
        self._result = result
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs) -> _FakeAudioResponse:
        self.last_kwargs = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return _FakeAudioResponse(self._result)


class _FakeAudioResource:
    def __init__(self, transcriptions: _FakeTranscriptions, speech: _FakeSpeech) -> None:
        self.transcriptions = transcriptions
        self.speech = speech


class FakeOpenAIClient:
    def __init__(self, transcriptions: _FakeTranscriptions, speech: _FakeSpeech) -> None:
        self.audio = _FakeAudioResource(transcriptions, speech)


def install_fake_voice_client(
    monkeypatch,
    transcript: str | Exception = "What are your hours?",
    audio: bytes | Exception = b"FAKE-MP3-BYTES",
) -> FakeOpenAIClient:
    transcriptions = _FakeTranscriptions(transcript)
    speech = _FakeSpeech(audio)
    fake_client = FakeOpenAIClient(transcriptions, speech)
    monkeypatch.setattr(voice, "get_openai_client", lambda: fake_client)
    return fake_client


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
    install_fake_voice_client(
        monkeypatch, transcript="What are your hours?", audio=b"FAKE-MP3-BYTES"
    )
    install_fake_client(monkeypatch, chunks=("We're open 9 to 5.",))

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "What are your hours?"
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "We're open 9 to 5."
    assert body["audio_mime"] == "audio/mpeg"
    assert base64.b64decode(body["audio_base64"]) == b"FAKE-MP3-BYTES"


async def test_voice_message_persists_both_turns(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Message

    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript="hello", audio=b"x")
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
    install_fake_voice_client(monkeypatch, transcript=RuntimeError("openai is down"))

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
        monkeypatch, transcript="hello", audio=RuntimeError("tts provider down")
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


async def test_voice_unavailable_when_no_api_key_configured(client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "openai_api_key", None)
    voice._reset_client_for_tests()

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
