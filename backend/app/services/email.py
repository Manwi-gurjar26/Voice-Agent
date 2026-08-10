"""Transactional email via Resend, with a local dev fallback.

No RESEND_API_KEY configured -> the email is logged instead of sent, so the
whole password-reset flow is testable against a local backend without a
Resend account. Uses raw httpx (already a dependency elsewhere in this
codebase) rather than Resend's own SDK — one REST call doesn't need a client
library.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"


async def _post_to_resend(payload: dict) -> httpx.Response:
    """The one actual network call — pulled out on its own so tests can
    monkeypatch just this, not httpx.AsyncClient itself (which the test
    client driving requests into this app is also an instance of)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await client.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )


async def send_password_reset_email(to_email: str, reset_url: str) -> None:
    subject = "Reset your password"
    html = (
        f"<p>Someone requested a password reset for this account.</p>"
        f'<p><a href="{reset_url}">Reset your password</a></p>'
        f"<p>This link expires in {settings.password_reset_token_expire_minutes} minutes. "
        f"If you didn't request this, you can ignore this email.</p>"
    )

    if not settings.resend_api_key:
        # Dev fallback: no provider configured, so there's nothing to send
        # through — logging the link is what makes this testable locally.
        logger.info("[password reset] no RESEND_API_KEY configured; reset link for %s: %s", to_email, reset_url)
        return

    try:
        response = await _post_to_resend(
            {
                "from": settings.email_from,
                "to": [to_email],
                "subject": subject,
                "html": html,
            }
        )
        if response.is_error:
            logger.error(
                "Resend email send failed for %s: %s %s",
                to_email,
                response.status_code,
                response.text,
            )
    except httpx.HTTPError:
        # Never let a network failure escape: request_password_reset's
        # response must look identical whether or not the address exists,
        # and that includes "the send failed" — this is caught and logged,
        # not raised, for the same reason response.is_error is only logged
        # above rather than raised.
        logger.exception("Could not reach Resend to send a password reset email to %s", to_email)
