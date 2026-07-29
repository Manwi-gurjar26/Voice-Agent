from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.db.session import get_db
from app.main import create_app
from app.models.widget_session import WidgetSession
from app.services import rate_limit
from tests.test_auth import bearer, register

PREFIX = settings.api_v1_prefix
ORIGIN = "https://shop.acme.example.com"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit._reset_for_tests()
    yield
    rate_limit._reset_for_tests()


async def make_active_agent(client, tokens, **overrides) -> dict:
    body = {"name": "Support Bot", "allowed_origins": [ORIGIN]} | overrides
    created = await client.post(f"{PREFIX}/agents", json=body, headers=bearer(tokens))
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    activated = await client.patch(
        f"{PREFIX}/agents/{agent_id}", json={"status": "active"}, headers=bearer(tokens)
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


# --------------------------------------------------------------------------
# Config endpoint
# --------------------------------------------------------------------------
async def test_config_is_served_for_an_allowed_origin(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.get(
        f"{PREFIX}/public/agents/{agent['public_key']}/config", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    assert response.json() == {
        "name": "Support Bot",
        "greeting": agent["greeting"],
        "voice_enabled": False,
        "theme": agent["theme"],
    }
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN


async def test_config_never_exposes_internal_fields(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.get(
        f"{PREFIX}/public/agents/{agent['public_key']}/config", headers={"Origin": ORIGIN}
    )
    body = response.text
    for leaked in (
        "system_prompt",
        "\"model\"",
        "\"effort\"",
        "allowed_origins",
        "rate_limit_per_minute",
        "tenant_id",
        "public_key",
    ):
        assert leaked not in body, leaked


async def test_config_rejects_a_disallowed_origin(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.get(
        f"{PREFIX}/public/agents/{agent['public_key']}/config",
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert "Access-Control-Allow-Origin" not in response.headers


async def test_config_rejects_a_missing_origin_header(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.get(f"{PREFIX}/public/agents/{agent['public_key']}/config")
    assert response.status_code == 403


async def test_config_404s_for_a_draft_agent(client):
    tokens = await register(client)
    created = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Still Draft", "allowed_origins": [ORIGIN]},
        headers=bearer(tokens),
    )
    agent = created.json()  # never activated

    response = await client.get(
        f"{PREFIX}/public/agents/{agent['public_key']}/config", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 404


async def test_config_404s_for_a_disabled_agent(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)
    await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"status": "disabled"}, headers=bearer(tokens)
    )

    response = await client.get(
        f"{PREFIX}/public/agents/{agent['public_key']}/config", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 404


async def test_config_404s_for_an_unknown_public_key(client):
    response = await client.get(
        f"{PREFIX}/public/agents/agt_pub_doesnotexist/config", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# CORS preflight
# --------------------------------------------------------------------------
async def test_preflight_for_an_allowed_origin_returns_204_with_headers(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.options(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


async def test_preflight_for_a_disallowed_origin_gets_no_cors_header(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.options(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response.headers


async def test_preflight_for_an_unknown_agent_gets_no_cors_header(client):
    response = await client.options(
        f"{PREFIX}/public/agents/agt_pub_doesnotexist/sessions",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    # 404, not 403: resolve_public_agent runs for real here (see
    # PublicWidgetCorsMiddleware's docstring), and an unknown public_key hits
    # its NotFoundError branch before the origin check ever runs.
    assert response.status_code == 404
    assert "Access-Control-Allow-Origin" not in response.headers


async def test_preflight_for_session_token_route_reflects_any_origin(client):
    """/public/sessions/me carries no public_key in its path, so preflight
    can't check an allowlist — enforcement happens inside the endpoint."""
    response = await client.options(
        f"{PREFIX}/public/sessions/me",
        headers={"Origin": "https://anything.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == "https://anything.example.com"


# --------------------------------------------------------------------------
# Session creation and validation
# --------------------------------------------------------------------------
async def test_create_session_returns_a_bearer_token(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.widget_session_expire_minutes * 60
    assert len(body["session_token"]) > 20


async def test_create_session_persists_a_row_scoped_to_the_right_tenant(client, db_session):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )

    row = await db_session.scalar(select(WidgetSession))
    assert row is not None
    assert str(row.agent_id) == agent["id"]
    assert row.origin == ORIGIN


async def test_create_session_rejects_a_disallowed_origin(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    response = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions",
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


async def test_session_token_validates_via_sessions_me(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    created = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    session_token = created.json()["session_token"]

    response = await client.get(
        f"{PREFIX}/public/sessions/me",
        headers={"Authorization": f"Bearer {session_token}", "Origin": ORIGIN},
    )
    assert response.status_code == 200
    assert response.json()["agent_id"] == agent["id"]


async def test_session_token_is_rejected_from_a_different_origin(client):
    """The origin re-check inside get_widget_session is the real access
    control for session-token routes — the permissive preflight is not."""
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    created = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    session_token = created.json()["session_token"]

    response = await client.get(
        f"{PREFIX}/public/sessions/me",
        headers={"Authorization": f"Bearer {session_token}", "Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


async def test_disabling_the_agent_invalidates_a_live_widget_session(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)

    created = await client.post(
        f"{PREFIX}/public/agents/{agent['public_key']}/sessions", headers={"Origin": ORIGIN}
    )
    session_token = created.json()["session_token"]
    assert (
        await client.get(
            f"{PREFIX}/public/sessions/me",
            headers={"Authorization": f"Bearer {session_token}", "Origin": ORIGIN},
        )
    ).status_code == 200

    await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"status": "disabled"}, headers=bearer(tokens)
    )

    response = await client.get(
        f"{PREFIX}/public/sessions/me",
        headers={"Authorization": f"Bearer {session_token}", "Origin": ORIGIN},
    )
    assert response.status_code == 401


async def test_an_access_token_is_not_accepted_as_a_widget_session(client):
    tokens = await register(client)
    response = await client.get(
        f"{PREFIX}/public/sessions/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}", "Origin": ORIGIN},
    )
    assert response.status_code == 401


async def test_unknown_session_token_is_rejected(client):
    response = await client.get(
        f"{PREFIX}/public/sessions/me",
        headers={"Authorization": "Bearer garbage", "Origin": ORIGIN},
    )
    assert response.status_code == 401


async def test_sessions_me_requires_a_token(client):
    response = await client.get(f"{PREFIX}/public/sessions/me", headers={"Origin": ORIGIN})
    assert response.status_code == 401


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------
async def test_rate_limit_kicks_in_after_the_configured_number_of_requests(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)
    await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"rate_limit_per_minute": 3}, headers=bearer(tokens)
    )

    url = f"{PREFIX}/public/agents/{agent['public_key']}/config"
    statuses = [(await client.get(url, headers={"Origin": ORIGIN})).status_code for _ in range(5)]

    assert statuses.count(200) == 3
    assert statuses.count(429) == 2


async def test_rate_limited_response_carries_a_retry_after_header(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)
    await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"rate_limit_per_minute": 1}, headers=bearer(tokens)
    )
    url = f"{PREFIX}/public/agents/{agent['public_key']}/config"

    await client.get(url, headers={"Origin": ORIGIN})
    response = await client.get(url, headers={"Origin": ORIGIN})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0


async def test_rate_limit_is_scoped_per_agent(client):
    tokens = await register(client)
    agent_a = await make_active_agent(client, tokens, name="Bot A")
    agent_b = await make_active_agent(client, tokens, name="Bot B")
    for agent in (agent_a, agent_b):
        await client.patch(
            f"{PREFIX}/agents/{agent['id']}",
            json={"rate_limit_per_minute": 1},
            headers=bearer(tokens),
        )

    url_a = f"{PREFIX}/public/agents/{agent_a['public_key']}/config"
    url_b = f"{PREFIX}/public/agents/{agent_b['public_key']}/config"

    assert (await client.get(url_a, headers={"Origin": ORIGIN})).status_code == 200
    assert (await client.get(url_a, headers={"Origin": ORIGIN})).status_code == 429
    # A different agent's budget is untouched by agent A's traffic.
    assert (await client.get(url_b, headers={"Origin": ORIGIN})).status_code == 200


# --------------------------------------------------------------------------
# Regression: dashboard CORS must not swallow public-route preflights
# --------------------------------------------------------------------------
async def test_public_preflight_still_works_when_dashboard_cors_is_configured(
    monkeypatch, db_session
):
    """With settings.dashboard_cors_origins set — the normal .env/production
    case, but NOT the default test environment — a widget preflight to
    /public/* must still get answered by the per-agent check, not swallowed
    by the dashboard's static allowlist. This is the exact bug a live smoke
    test caught: Starlette's CORSMiddleware intercepts any OPTIONS request
    carrying Access-Control-Request-Method, from any path, before the router
    or a wrapping middleware ever sees it — silently breaking every widget
    integration in every environment where dashboard CORS is configured.
    """
    monkeypatch.setattr(settings, "dashboard_cors_origins", ["http://localhost:3000"])
    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as scoped_client:
        tokens = await register(scoped_client)
        agent = await make_active_agent(scoped_client, tokens)

        response = await scoped_client.options(
            f"{PREFIX}/public/agents/{agent['public_key']}/config",
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET"},
        )
        assert response.status_code == 204
        assert response.headers["Access-Control-Allow-Origin"] == ORIGIN

        # And the dashboard's own CORS still works, unaffected.
        dashboard_preflight = await scoped_client.options(
            f"{PREFIX}/auth/me",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert dashboard_preflight.status_code == 204
        assert (
            dashboard_preflight.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
        )


async def test_session_creation_shares_the_same_budget_as_config_reads(client):
    tokens = await register(client)
    agent = await make_active_agent(client, tokens)
    await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"rate_limit_per_minute": 1}, headers=bearer(tokens)
    )

    config_url = f"{PREFIX}/public/agents/{agent['public_key']}/config"
    sessions_url = f"{PREFIX}/public/agents/{agent['public_key']}/sessions"

    assert (await client.get(config_url, headers={"Origin": ORIGIN})).status_code == 200
    assert (await client.post(sessions_url, headers={"Origin": ORIGIN})).status_code == 429
