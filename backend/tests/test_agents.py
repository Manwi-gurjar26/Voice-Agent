from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import Agent, User
from app.models.enums import UserRole
from tests.test_auth import PASSWORD, bearer, register

PREFIX = settings.api_v1_prefix


async def make_agent(client, tokens, **overrides) -> dict:
    body = {"name": "Support Bot", "allowed_origins": ["https://shop.acme.example.com"]} | overrides
    response = await client.post(f"{PREFIX}/agents", json=body, headers=bearer(tokens))
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# CRUD
# --------------------------------------------------------------------------
async def test_create_agent_applies_defaults_and_returns_an_embed_snippet(client):
    tokens = await register(client)
    agent = await make_agent(client, tokens)

    assert agent["public_key"].startswith("agt_pub_")
    assert agent["status"] == "draft"
    assert agent["model"] == "claude-opus-5"
    assert agent["effort"] == "medium"
    assert agent["theme"]["primaryColor"] == "#2F6FED"
    assert agent["public_key"] in agent["embed_snippet"]
    assert agent["embed_snippet"].startswith("<script")


async def test_list_returns_only_this_tenants_agents(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")

    await make_agent(client, tokens_a, name="Acme Bot")
    await make_agent(client, tokens_b, name="Globex Bot")

    listing = (await client.get(f"{PREFIX}/agents", headers=bearer(tokens_a))).json()
    assert listing["total"] == 1
    assert [a["name"] for a in listing["items"]] == ["Acme Bot"]


async def test_patch_updates_only_the_supplied_fields(client):
    tokens = await register(client)
    agent = await make_agent(client, tokens, greeting="Original greeting")

    response = await client.patch(
        f"{PREFIX}/agents/{agent['id']}",
        json={"status": "active", "effort": "xhigh"},
        headers=bearer(tokens),
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "active"
    assert updated["effort"] == "xhigh"
    assert updated["greeting"] == "Original greeting"   # untouched
    assert updated["public_key"] == agent["public_key"]  # never regenerated


async def test_delete_removes_the_agent(client, db_session):
    tokens = await register(client)
    agent = await make_agent(client, tokens)

    assert (
        await client.delete(f"{PREFIX}/agents/{agent['id']}", headers=bearer(tokens))
    ).status_code == 204
    assert (
        await client.get(f"{PREFIX}/agents/{agent['id']}", headers=bearer(tokens))
    ).status_code == 404


async def test_duplicate_agent_name_within_a_tenant_is_rejected(client):
    tokens = await register(client)
    await make_agent(client, tokens, name="Support Bot")
    response = await client.post(
        f"{PREFIX}/agents", json={"name": "Support Bot"}, headers=bearer(tokens)
    )
    assert response.status_code == 409


async def test_same_agent_name_in_different_tenants_is_allowed(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")

    await make_agent(client, tokens_a, name="Support Bot")
    await make_agent(client, tokens_b, name="Support Bot")


async def test_pagination(client):
    tokens = await register(client)
    for i in range(3):
        await make_agent(client, tokens, name=f"Bot {i}")

    page = (
        await client.get(f"{PREFIX}/agents?limit=2&offset=0", headers=bearer(tokens))
    ).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2


# --------------------------------------------------------------------------
# Tenant isolation
# --------------------------------------------------------------------------
async def test_cannot_read_another_tenants_agent(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent = await make_agent(client, tokens_a)

    response = await client.get(f"{PREFIX}/agents/{agent['id']}", headers=bearer(tokens_b))
    # 404, not 403: a 403 would confirm the id exists.
    assert response.status_code == 404


async def test_cannot_update_another_tenants_agent(client, db_session):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent = await make_agent(client, tokens_a)

    response = await client.patch(
        f"{PREFIX}/agents/{agent['id']}", json={"name": "Hijacked"}, headers=bearer(tokens_b)
    )
    assert response.status_code == 404

    row = await db_session.scalar(select(Agent).where(Agent.id == agent["id"]))
    assert row.name == "Support Bot"


async def test_cannot_delete_another_tenants_agent(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent = await make_agent(client, tokens_a)

    assert (
        await client.delete(f"{PREFIX}/agents/{agent['id']}", headers=bearer(tokens_b))
    ).status_code == 404
    assert (
        await client.get(f"{PREFIX}/agents/{agent['id']}", headers=bearer(tokens_a))
    ).status_code == 200


async def test_tenant_id_in_the_body_cannot_reassign_an_agent(client, db_session):
    """tenant_id is not part of AgentCreate/AgentUpdate, so an injected value is
    ignored rather than honoured."""
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")

    victim = await db_session.scalar(select(User).where(User.email == "b@globex.example.com"))
    response = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Injected", "tenant_id": str(victim.tenant_id)},
        headers=bearer(tokens_a),
    )
    assert response.status_code == 201

    attacker = await db_session.scalar(select(User).where(User.email == "a@acme.example.com"))
    row = await db_session.scalar(select(Agent).where(Agent.name == "Injected"))
    assert row.tenant_id == attacker.tenant_id


async def test_requests_without_a_token_are_rejected(client):
    assert (await client.get(f"{PREFIX}/agents")).status_code == 401
    assert (await client.post(f"{PREFIX}/agents", json={"name": "X"})).status_code == 401


# --------------------------------------------------------------------------
# Role-based access
# --------------------------------------------------------------------------
async def _member_tokens(client, db_session) -> dict:
    owner = await register(client)
    tenant_id = (
        await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    ).tenant_id
    db_session.add(
        User(
            tenant_id=tenant_id,
            email="member@acme.example.com",
            hashed_password=hash_password(PASSWORD),
            role=UserRole.MEMBER,
        )
    )
    await db_session.flush()
    response = await client.post(
        f"{PREFIX}/auth/login", json={"email": "member@acme.example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    return owner, response.json()


async def test_member_can_read_agents(client, db_session):
    owner, member = await _member_tokens(client, db_session)
    await make_agent(client, owner)

    response = await client.get(f"{PREFIX}/agents", headers=bearer(member))
    assert response.status_code == 200
    assert response.json()["total"] == 1


async def test_member_cannot_create_or_delete_agents(client, db_session):
    owner, member = await _member_tokens(client, db_session)
    agent = await make_agent(client, owner)

    created = await client.post(
        f"{PREFIX}/agents", json={"name": "Member Bot"}, headers=bearer(member)
    )
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "forbidden"

    deleted = await client.delete(f"{PREFIX}/agents/{agent['id']}", headers=bearer(member))
    assert deleted.status_code == 403


# --------------------------------------------------------------------------
# Origin allowlist validation
# --------------------------------------------------------------------------
async def test_origins_are_normalised_and_deduplicated(client):
    tokens = await register(client)
    agent = await make_agent(
        client,
        tokens,
        allowed_origins=[
            "https://Shop.Acme.example.com/checkout?a=1",
            "https://shop.acme.example.com",
            "http://localhost:3000",
        ],
    )
    assert agent["allowed_origins"] == ["https://shop.acme.example.com", "http://localhost:3000"]


async def test_plain_http_origins_are_rejected_except_localhost(client):
    tokens = await register(client)
    response = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Insecure", "allowed_origins": ["http://shop.acme.example.com"]},
        headers=bearer(tokens),
    )
    assert response.status_code == 422


async def test_origin_without_a_scheme_is_rejected(client):
    tokens = await register(client)
    response = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Bad", "allowed_origins": ["shop.acme.example.com"]},
        headers=bearer(tokens),
    )
    assert response.status_code == 422


async def test_non_http_scheme_is_rejected(client):
    tokens = await register(client)
    response = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Bad", "allowed_origins": ["javascript://evil"]},
        headers=bearer(tokens),
    )
    assert response.status_code == 422


async def test_max_output_tokens_is_bounded(client):
    tokens = await register(client)
    response = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Huge", "max_output_tokens": 999_999},
        headers=bearer(tokens),
    )
    assert response.status_code == 422


async def test_unknown_effort_level_is_rejected(client):
    tokens = await register(client)
    response = await client.post(
        f"{PREFIX}/agents",
        json={"name": "Creative", "effort": "creative"},
        headers=bearer(tokens),
    )
    assert response.status_code == 422


async def test_temperature_is_not_a_settable_field(client):
    """Current Claude models reject temperature; the field must not exist."""
    tokens = await register(client)
    agent = await make_agent(client, tokens, temperature=0.7)
    assert "temperature" not in agent
