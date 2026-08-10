from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import PasswordResetToken
from app.services import auth as auth_service
from app.services import email as email_service
from app.services import rate_limit
from tests.test_auth import PASSWORD, register

PREFIX = settings.api_v1_prefix
EMAIL = "owner@acme.example.com"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._reset_for_tests()
    yield
    rate_limit._reset_for_tests()


def _capture_reset_urls(monkeypatch) -> list[str]:
    """Monkeypatches the seam auth_service.request_password_reset actually
    calls, capturing the reset_url it's given — the only place the plaintext
    token appears, since only its hash is ever stored. Mirrors this
    codebase's established pattern of faking at the service seam (see
    test_billing.py's install_fake_checkout, test_voice.py's
    install_fake_voice_client) rather than the network layer beneath it."""
    captured: list[str] = []

    async def fake_send(to_email: str, reset_url: str) -> None:
        captured.append(reset_url)

    monkeypatch.setattr(auth_service, "send_password_reset_email", fake_send)
    return captured


async def _get_reset_token(client, monkeypatch, email: str = EMAIL) -> str:
    urls = _capture_reset_urls(monkeypatch)
    response = await client.post(f"{PREFIX}/auth/forgot-password", json={"email": email})
    assert response.status_code == 202, response.text
    assert len(urls) == 1
    return urls[0].rsplit("token=", 1)[1]


# --------------------------------------------------------------------------
# Requesting a reset
# --------------------------------------------------------------------------
async def test_forgot_password_for_a_known_email_creates_a_token(client, db_session, monkeypatch):
    await register(client)
    reset_token = await _get_reset_token(client, monkeypatch)

    assert reset_token
    stored = await db_session.scalar(select(PasswordResetToken))
    assert stored is not None
    # The stored value is a hash, not the plaintext handed to the caller.
    assert stored.token_hash != reset_token


async def test_forgot_password_for_an_unknown_email_is_identical_and_creates_nothing(
    client, db_session, monkeypatch
):
    urls = _capture_reset_urls(monkeypatch)
    response = await client.post(
        f"{PREFIX}/auth/forgot-password", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 202
    assert urls == []  # never even attempted to send
    assert await db_session.scalar(select(PasswordResetToken)) is None


async def test_forgot_password_falls_back_to_logging_without_a_resend_key(client, monkeypatch):
    """No RESEND_API_KEY -> send_password_reset_email's own dev fallback
    (logging, not a network call) runs — verified here by confirming no
    outbound Resend call happens, not by asserting on log output (this
    project's Alembic env.py calls logging.config.fileConfig via the
    session-scoped migration fixture, which disables any logger created
    after that point by default — a pre-existing test-infra quirk unrelated
    to this feature, worked around rather than fixed here)."""
    monkeypatch.setattr(settings, "resend_api_key", None)
    posted = False

    async def fake_post_to_resend(payload: dict):
        nonlocal posted
        posted = True
        raise AssertionError("should not be called when resend_api_key is unset")

    monkeypatch.setattr(email_service, "_post_to_resend", fake_post_to_resend)

    await register(client)
    response = await client.post(f"{PREFIX}/auth/forgot-password", json={"email": EMAIL})

    assert response.status_code == 202
    assert posted is False


async def test_forgot_password_sends_via_resend_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_fake")
    calls: list[dict] = []

    async def fake_post_to_resend(payload: dict) -> httpx.Response:
        calls.append(payload)
        return httpx.Response(200, request=httpx.Request("POST", email_service._RESEND_URL))

    monkeypatch.setattr(email_service, "_post_to_resend", fake_post_to_resend)

    await register(client)
    response = await client.post(f"{PREFIX}/auth/forgot-password", json={"email": EMAIL})

    assert response.status_code == 202
    assert len(calls) == 1
    assert calls[0]["to"] == [EMAIL]
    assert calls[0]["from"] == settings.email_from


async def test_forgot_password_survives_resend_being_unreachable(client, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_fake")

    async def fake_post_to_resend(payload: dict) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(email_service, "_post_to_resend", fake_post_to_resend)

    await register(client)
    response = await client.post(f"{PREFIX}/auth/forgot-password", json={"email": EMAIL})

    # Still 202 — a network failure to the email provider must not surface
    # differently than the identical-response-regardless-of-existence path.
    assert response.status_code == 202


async def test_forgot_password_survives_resend_returning_an_error(client, monkeypatch):
    monkeypatch.setattr(settings, "resend_api_key", "re_test_fake")

    async def fake_post_to_resend(payload: dict) -> httpx.Response:
        return httpx.Response(
            422, json={"message": "invalid"}, request=httpx.Request("POST", email_service._RESEND_URL)
        )

    monkeypatch.setattr(email_service, "_post_to_resend", fake_post_to_resend)

    await register(client)
    response = await client.post(f"{PREFIX}/auth/forgot-password", json={"email": EMAIL})

    assert response.status_code == 202


async def test_forgot_password_is_rate_limited(client):
    for _ in range(5):
        response = await client.post(
            f"{PREFIX}/auth/forgot-password", json={"email": "nobody@example.com"}
        )
        assert response.status_code == 202

    response = await client.post(
        f"{PREFIX}/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers


# --------------------------------------------------------------------------
# Redeeming a reset
# --------------------------------------------------------------------------
async def test_reset_password_happy_path_revokes_old_sessions(client, monkeypatch):
    tokens = await register(client)
    reset_token = await _get_reset_token(client, monkeypatch)

    response = await client.post(
        f"{PREFIX}/auth/reset-password",
        json={"token": reset_token, "password": "new-correct-horse-99"},
    )
    assert response.status_code == 204

    refresh_response = await client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_response.status_code == 401

    new_login = await client.post(
        f"{PREFIX}/auth/login", json={"email": EMAIL, "password": "new-correct-horse-99"}
    )
    assert new_login.status_code == 200

    old_login = await client.post(f"{PREFIX}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert old_login.status_code == 401


async def test_reset_password_token_is_single_use(client, monkeypatch):
    await register(client)
    reset_token = await _get_reset_token(client, monkeypatch)

    first = await client.post(
        f"{PREFIX}/auth/reset-password",
        json={"token": reset_token, "password": "new-correct-horse-99"},
    )
    assert first.status_code == 204

    second = await client.post(
        f"{PREFIX}/auth/reset-password",
        json={"token": reset_token, "password": "another-correct-horse-1"},
    )
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "invalid_reset_token"


async def test_reset_password_expired_token_is_rejected(client, db_session, monkeypatch):
    await register(client)
    reset_token = await _get_reset_token(client, monkeypatch)

    record = await db_session.scalar(select(PasswordResetToken))
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    response = await client.post(
        f"{PREFIX}/auth/reset-password",
        json={"token": reset_token, "password": "new-correct-horse-99"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_reset_token"


async def test_reset_password_garbage_token_is_rejected(client):
    response = await client.post(
        f"{PREFIX}/auth/reset-password",
        json={"token": "not-a-real-token", "password": "new-correct-horse-99"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_reset_token"


async def test_reset_password_enforces_the_password_policy(client, monkeypatch):
    await register(client)
    reset_token = await _get_reset_token(client, monkeypatch)

    response = await client.post(
        f"{PREFIX}/auth/reset-password", json={"token": reset_token, "password": "short"}
    )
    assert response.status_code == 422
