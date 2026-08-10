from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.models import RefreshToken, User

PREFIX = settings.api_v1_prefix
PASSWORD = "correct-horse-9-battery"


def signup_body(email: str = "owner@acme.example.com", company: str = "Acme Inc") -> dict:
    return {
        "email": email,
        "password": PASSWORD,
        "full_name": "Ada Lovelace",
        "company_name": company,
    }


async def register(client, **kwargs) -> dict:
    response = await client.post(f"{PREFIX}/auth/signup", json=signup_body(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --------------------------------------------------------------------------
# Signup
# --------------------------------------------------------------------------
async def test_signup_creates_tenant_and_owner(client, db_session):
    tokens = await register(client)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == settings.access_token_expire_minutes * 60

    me = await client.get(f"{PREFIX}/auth/me", headers=bearer(tokens))
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == "owner@acme.example.com"
    assert body["user"]["role"] == "owner"
    assert body["tenant"]["name"] == "Acme Inc"
    assert body["tenant"]["slug"] == "acme-inc"
    assert body["tenant"]["plan"] == "free"


async def test_signup_never_returns_the_password_hash(client):
    tokens = await register(client)
    me = await client.get(f"{PREFIX}/auth/me", headers=bearer(tokens))
    assert "hashed_password" not in me.text
    assert PASSWORD not in me.text


async def test_duplicate_email_is_rejected(client):
    await register(client)
    response = await client.post(f"{PREFIX}/auth/signup", json=signup_body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_duplicate_company_name_is_rejected(client):
    await register(client, email="a@acme.example.com")
    response = await client.post(
        f"{PREFIX}/auth/signup", json=signup_body(email="b@acme.example.com")
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert "workspace" in response.json()["error"]["message"].lower()


async def test_duplicate_company_name_is_rejected_case_insensitively(client):
    await register(client, email="a@acme.example.com", company="Acme Inc")
    response = await client.post(
        f"{PREFIX}/auth/signup",
        json=signup_body(email="b@acme.example.com", company="ACME INC"),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


async def test_distinct_company_names_both_succeed(client):
    first = await register(client, email="a@acme.example.com", company="Acme Inc")
    second = await register(client, email="b@acme.example.com", company="Widgets LLC")

    slug_a = (await client.get(f"{PREFIX}/auth/me", headers=bearer(first))).json()["tenant"]["slug"]
    slug_b = (await client.get(f"{PREFIX}/auth/me", headers=bearer(second))).json()["tenant"]["slug"]
    assert slug_a != slug_b


async def test_email_is_normalised_to_lowercase(client):
    await register(client, email="Owner@ACME.example.com")
    login = await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_short_password_is_rejected(client):
    body = signup_body() | {"password": "short1!"}
    response = await client.post(f"{PREFIX}/auth/signup", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_all_letter_password_is_rejected(client):
    body = signup_body() | {"password": "abcdefghijklmnop"}
    response = await client.post(f"{PREFIX}/auth/signup", json=body)
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------
async def test_login_succeeds_and_stamps_last_login(client, db_session):
    await register(client)
    response = await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
    )
    assert response.status_code == 200

    user = await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    assert user.last_login_at is not None


async def test_wrong_password_and_unknown_email_are_indistinguishable(client):
    await register(client)
    wrong = await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": "wrong-password-1"}
    )
    unknown = await client.post(
        f"{PREFIX}/auth/login", json={"email": "nobody@acme.example.com", "password": "wrong-password-1"}
    )

    assert wrong.status_code == unknown.status_code == 401
    # Identical body: a different message would let an attacker enumerate users.
    assert wrong.json() == unknown.json()


async def test_deactivated_user_cannot_log_in(client, db_session):
    await register(client)
    user = await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    user.is_active = False
    await db_session.flush()

    response = await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
    )
    assert response.status_code == 401


async def test_repeated_failures_lock_the_account(client, db_session):
    await register(client)
    for _ in range(settings.max_failed_logins):
        await client.post(
            f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": "wrong-pass-11"}
        )

    # Correct password is now refused too — that is what makes lockout useful.
    response = await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "account_locked"


async def test_successful_login_clears_the_failure_counter(client, db_session):
    await register(client)
    await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": "wrong-pass-11"}
    )
    await client.post(
        f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
    )

    user = await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


# --------------------------------------------------------------------------
# Refresh rotation
# --------------------------------------------------------------------------
async def test_refresh_returns_a_new_pair_and_revokes_the_old_token(client, db_session):
    tokens = await register(client)
    response = await client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    rotated = response.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]

    records = list(await db_session.scalars(select(RefreshToken)))
    assert len(records) == 2
    assert sum(1 for r in records if r.revoked_at is not None) == 1
    # Rotation stays within one family so reuse detection can span the chain.
    assert len({r.family_id for r in records}) == 1


async def test_refresh_tokens_are_never_stored_in_plaintext(client, db_session):
    tokens = await register(client)
    stored = list(await db_session.scalars(select(RefreshToken.token_hash)))
    assert tokens["refresh_token"] not in stored


async def test_reusing_a_rotated_token_revokes_the_whole_family(client, db_session):
    tokens = await register(client)
    rotated = (
        await client.post(f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    ).json()

    # Replay the already-consumed token — the signature of a stolen token.
    replay = await client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401

    # The legitimate holder's newer token is revoked too: once a token in the
    # chain has leaked, the session can no longer be trusted.
    after = await client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert after.status_code == 401

    records = list(await db_session.scalars(select(RefreshToken)))
    assert all(r.revoked_at is not None for r in records)


async def test_unknown_refresh_token_is_rejected(client):
    response = await client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": "not-a-real-token"}
    )
    assert response.status_code == 401


async def test_expired_refresh_token_is_rejected(client, db_session):
    tokens = await register(client)
    record = await db_session.scalar(select(RefreshToken))
    record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.flush()

    response = await client.post(
        f"{PREFIX}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Logout
# --------------------------------------------------------------------------
async def test_logout_revokes_only_that_session(client, db_session):
    first = await register(client)
    second = (
        await client.post(
            f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
        )
    ).json()

    response = await client.post(
        f"{PREFIX}/auth/logout", json={"refresh_token": first["refresh_token"]}
    )
    assert response.status_code == 204

    assert (
        await client.post(f"{PREFIX}/auth/refresh", json={"refresh_token": first["refresh_token"]})
    ).status_code == 401
    assert (
        await client.post(f"{PREFIX}/auth/refresh", json={"refresh_token": second["refresh_token"]})
    ).status_code == 200


async def test_logout_with_an_unknown_token_still_succeeds(client):
    """Logout must not reveal whether a token existed."""
    response = await client.post(f"{PREFIX}/auth/logout", json={"refresh_token": "made-up"})
    assert response.status_code == 204


async def test_logout_all_revokes_every_session(client, db_session):
    tokens = await register(client)
    second = (
        await client.post(
            f"{PREFIX}/auth/login", json={"email": "owner@acme.example.com", "password": PASSWORD}
        )
    ).json()

    response = await client.post(f"{PREFIX}/auth/logout-all", headers=bearer(tokens))
    assert response.status_code == 204

    for token in (tokens["refresh_token"], second["refresh_token"]):
        assert (
            await client.post(f"{PREFIX}/auth/refresh", json={"refresh_token": token})
        ).status_code == 401


# --------------------------------------------------------------------------
# Access token handling
# --------------------------------------------------------------------------
async def test_me_requires_a_token(client):
    response = await client.get(f"{PREFIX}/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_garbage_token_is_rejected(client):
    response = await client.get(
        f"{PREFIX}/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
    )
    assert response.status_code == 401


async def test_refresh_token_is_not_accepted_as_an_access_token(client):
    tokens = await register(client)
    response = await client.get(
        f"{PREFIX}/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert response.status_code == 401


async def test_deactivating_a_user_invalidates_their_live_access_token(client, db_session):
    """Access tokens are re-checked against the database on every request, so
    revocation does not wait for the token to expire."""
    tokens = await register(client)
    assert (await client.get(f"{PREFIX}/auth/me", headers=bearer(tokens))).status_code == 200

    user = await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    user.is_active = False
    await db_session.flush()

    assert (await client.get(f"{PREFIX}/auth/me", headers=bearer(tokens))).status_code == 401
