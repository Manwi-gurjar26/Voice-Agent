from __future__ import annotations

import base64

from app.core.config import settings
from app.services import groq_llm, voice
from tests.test_auth import register
from tests.test_chat import make_widget_session, session_auth
from tests.test_public import make_active_agent

PREFIX = settings.api_v1_prefix

AUDIO_BYTES = b"pretend-this-is-a-webm-audio-clip"


# --------------------------------------------------------------------------
# Fakes at the two network seams a voice turn actually uses:
# voice.transcribe_audio/synthesize_speech (Groq STT / Fish Audio TTS,
# called directly — no client-object seam for either, see voice.py) and
# groq_llm.get_groq_client (the LLM step in chat_service.complete_turn).
# Mirrors test_chat.py's install_fake_client for the analogous Gemini seam.
# Real model behavior is covered separately in test_voice_models.py.
# --------------------------------------------------------------------------
def install_fake_voice_client(
    monkeypatch,
    transcript: str | Exception = "What are your hours?",
    tts_fail: Exception | None = None,
) -> None:
    async def fake_transcribe(audio_bytes: bytes, filename: str) -> str:
        if isinstance(transcript, Exception):
            raise transcript
        return transcript.strip()  # transcribe_audio's real contract: always stripped

    async def fake_synthesize(text: str, voice_id: str | None) -> bytes:
        if tts_fail:
            raise tts_fail
        return b"\xff\xfb\x90\x00fake-mp3-bytes"

    monkeypatch.setattr(voice, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(voice, "synthesize_speech", fake_synthesize)


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


class _FakeGroqCompletions:
    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs) -> _FakeGroqResponse:
        self.last_kwargs = kwargs
        if isinstance(self._reply, Exception):
            raise self._reply
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
    install_fake_groq_client(monkeypatch, reply="We're open 9 to 5.")

    conv_id = await make_voice_conversation(client, session)
    response = await post_voice_message(client, conv_id, session)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "What are your hours?"
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "We're open 9 to 5."
    assert body["audio_mime"] == "audio/mpeg"
    assert base64.b64decode(body["audio_base64"]) == b"\xff\xfb\x90\x00fake-mp3-bytes"


async def test_voice_message_persists_both_turns(client, monkeypatch, db_session):
    from sqlalchemy import select

    from app.models import Message

    tokens = await register(client)
    _agent, session = await make_widget_session(client, tokens, voice_enabled=True)
    install_fake_voice_client(monkeypatch, transcript="hello")
    install_fake_groq_client(monkeypatch, reply="hi there")

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
    install_fake_groq_client(monkeypatch, reply=RuntimeError("groq is down"))

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
    install_fake_groq_client(monkeypatch, reply="hi there")

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
    install_fake_groq_client(monkeypatch, reply="should not be reached")

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
    """Simulated directly at the seam rather than actually breaking network
    access — the real transcribe_audio already translates a Groq-reachability
    failure into VoiceUnavailableError (see its except clause)."""

    async def _raise(audio_bytes: bytes, filename: str) -> str:
        raise voice.VoiceUnavailableError("model unavailable")

    monkeypatch.setattr(voice, "transcribe_audio", _raise)

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


# --------------------------------------------------------------------------
# Speakable-text flattening
#
# Fish Audio reads markdown punctuation aloud and garbles the surrounding
# words — confirmed against the real API by synthesizing a formatted reply
# and transcribing the audio back, which returned "used to asterisk asterisk
# manage state asterisk asterisk manage state", repeating the phrase.
# --------------------------------------------------------------------------
def test_emphasis_and_code_markers_are_not_spoken():
    spoken = voice.to_speakable_text("It is used to **manage state** via `useReducer`.")
    assert spoken == "It is used to manage state via useReducer."


def test_bullets_become_separate_sentences_so_speech_pauses():
    spoken = voice.to_speakable_text("You can apply for:\n\n* Home Loan\n* Personal Loan")
    assert spoken == "You can apply for: Home Loan. Personal Loan."


def test_emoji_are_dropped_rather_than_read_out_by_name():
    spoken = voice.to_speakable_text("* \U0001f3e0 **Home Loan**\n* \U0001f4b3 **Personal Loan**")
    assert spoken == "Home Loan. Personal Loan."


def test_code_blocks_and_headings_are_removed():
    spoken = voice.to_speakable_text(
        "## EMI Calculator\n\nUse it:\n\n```python\nemi = p * r\n```\n\nIt shows the payment."
    )
    assert spoken == "EMI Calculator. Use it: It shows the payment."


def test_links_keep_their_text_and_drop_the_url():
    spoken = voice.to_speakable_text("See [the EMI calculator](https://example.com/emi) for details.")
    assert spoken == "See the EMI calculator for details."


def test_plain_prose_is_left_alone():
    original = "You can apply for Home Loans, Personal Loans, and Business Loans."
    assert voice.to_speakable_text(original) == original


def test_a_reply_that_is_only_a_code_block_still_synthesizes_something():
    # Better to read the code aloud than to hand the synthesizer an empty
    # string and play the visitor silence.
    spoken = voice.to_speakable_text("```\nemi = p * r\n```")
    assert spoken


async def test_synthesis_sends_the_flattened_text_not_the_raw_markdown(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        content = b"audio"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setattr(voice.httpx, "AsyncClient", lambda **_kw: FakeClient())

    await voice.synthesize_speech("Use **bold** and `code`.", None)

    assert captured["text"] == "Use bold and code."
