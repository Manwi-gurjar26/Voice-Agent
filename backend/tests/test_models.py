from __future__ import annotations

import pytest

from app.db.base import Base
from app.models import Agent, Tenant, User


def test_all_expected_tables_are_registered():
    assert set(Base.metadata.tables) == {
        "tenants",
        "users",
        "agents",
        "refresh_tokens",
        "password_reset_tokens",
        "widget_sessions",
        "conversations",
        "messages",
        "documents",
        "chunks",
    }


def test_tenant_scoped_foreign_keys_cascade():
    """Deleting a tenant must not strand its users or agents."""
    for model in (User, Agent):
        fk = next(iter(model.__table__.c.tenant_id.foreign_keys))
        assert fk.ondelete == "CASCADE", model.__name__


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.com", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com/some/path?q=1", "https://example.com"),
        ("  http://localhost:3000  ", "http://localhost:3000"),
        ("HTTPS://SHOP.EXAMPLE.CO.UK:8443/x", "https://shop.example.co.uk:8443"),
    ],
)
def test_origin_normalisation(raw, expected):
    assert Agent.normalize_origin(raw) == expected


@pytest.mark.parametrize("bad", ["example.com", "/just/a/path", "", "   "])
def test_origin_without_scheme_or_host_is_rejected(bad):
    with pytest.raises(ValueError):
        Agent.normalize_origin(bad)


def test_origin_allowlist_matches_normalised_entries():
    agent = Agent(allowed_origins=["https://shop.example.com"])

    assert agent.is_origin_allowed("https://shop.example.com")
    assert agent.is_origin_allowed("https://SHOP.example.com/")


def test_origin_allowlist_denies_lookalikes_and_scheme_downgrades():
    agent = Agent(allowed_origins=["https://shop.example.com"])

    assert not agent.is_origin_allowed("http://shop.example.com")       # scheme downgrade
    assert not agent.is_origin_allowed("https://shop.example.com.evil.io")
    assert not agent.is_origin_allowed("https://evil.com")
    assert not agent.is_origin_allowed("https://shop.example.com:8443")  # different port


def test_empty_allowlist_denies_everything():
    """Fail closed: an unconfigured agent must not be embeddable anywhere."""
    agent = Agent(allowed_origins=[])

    assert not agent.is_origin_allowed("https://anything.com")
    assert not agent.is_origin_allowed(None)


def test_agent_does_not_expose_a_temperature_column():
    """This app exposes only `effort` (-> Gemini's thinking_budget) as its
    one reasoning-depth/token-spend knob, not temperature/top_p/top_k."""
    columns = set(Agent.__table__.c.keys())
    assert {"temperature", "top_p", "top_k"}.isdisjoint(columns)
    assert "effort" in columns


def test_tenant_relationships_are_lazy_raise():
    """Guards against N+1 queries: relationship access must be explicit
    (selectinload/joinedload) rather than silently emitting a query."""
    assert Tenant.__mapper__.relationships["agents"].lazy == "raise"
    assert Tenant.__mapper__.relationships["users"].lazy == "raise"
