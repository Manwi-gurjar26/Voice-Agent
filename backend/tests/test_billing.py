from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import Tenant, User
from app.models.enums import PlanTier, UserRole
from app.services import billing
from tests.test_auth import PASSWORD, bearer, register

PREFIX = settings.api_v1_prefix


@pytest.fixture(autouse=True)
def _billing_settings(monkeypatch):
    monkeypatch.setattr(settings, "dodo_api_key", "sk_test_fake")
    monkeypatch.setattr(settings, "dodo_webhook_key", "whsec_" + base64.b64encode(b"0" * 24).decode())
    monkeypatch.setattr(settings, "dodo_product_id_starter", "pdt_starter")
    monkeypatch.setattr(settings, "dodo_product_id_pro", "pdt_pro")
    monkeypatch.setattr(settings, "dodo_product_id_enterprise", "pdt_enterprise")
    # The client seam caches its instance at module scope (see get_dodo_client),
    # same as llm.py/voice.py — must be reset so webhook tests (which use the
    # *real* client for real signature verification) pick up each test's
    # monkeypatched dodo_webhook_key instead of a stale cached client.
    billing._reset_client_for_tests()
    yield
    billing._reset_client_for_tests()


# --------------------------------------------------------------------------
# Fake Dodo client — the seam is get_dodo_client() itself, a real constructed
# object (unlike stripe-python's per-call api_key style), so one monkeypatch
# covers both checkout_sessions.create and customers.customer_portal.create.
# --------------------------------------------------------------------------
class _FakeDodoClient:
    def __init__(
        self,
        checkout_url: str = "https://checkout.dodopayments.com/test-session",
        portal_url: str = "https://customer-portal.dodopayments.com/test-portal",
    ) -> None:
        self.checkout_calls: list[dict] = []
        self.portal_calls: list[dict] = []
        self._checkout_url = checkout_url
        self._portal_url = portal_url
        self.checkout_sessions = SimpleNamespace(create=self._create_checkout)
        self.customers = SimpleNamespace(
            customer_portal=SimpleNamespace(create=self._create_portal)
        )

    async def _create_checkout(self, **kwargs):
        self.checkout_calls.append(kwargs)
        return SimpleNamespace(checkout_url=self._checkout_url)

    async def _create_portal(self, customer_id, **kwargs):
        self.portal_calls.append({"customer_id": customer_id, **kwargs})
        return SimpleNamespace(link=self._portal_url)


def install_fake_dodo_client(monkeypatch) -> _FakeDodoClient:
    fake = _FakeDodoClient()
    monkeypatch.setattr(billing, "get_dodo_client", lambda: fake)
    return fake


# --------------------------------------------------------------------------
# Webhook signing — replicates the Standard Webhooks HMAC scheme Dodo uses,
# by hand, so webhook tests exercise the real client.webhooks.unwrap path
# (via billing.construct_webhook_event) rather than a mocked verifier. Same
# rigor as the old Stripe-by-hand HMAC tests.
# --------------------------------------------------------------------------
def sign_dodo_payload(payload: bytes, secret: str, msg_id: str = "msg_test") -> dict[str, str]:
    timestamp = str(int(time.time()))
    key_bytes = base64.b64decode(secret.removeprefix("whsec_"))
    signed_content = f"{msg_id}.{timestamp}.{payload.decode()}"
    sig = base64.b64encode(hmac.new(key_bytes, signed_content.encode(), hashlib.sha256).digest())
    return {
        "webhook-id": msg_id,
        "webhook-signature": f"v1,{sig.decode()}",
        "webhook-timestamp": timestamp,
    }


async def post_webhook(client, event: dict, secret: str | None = None):
    payload = json.dumps(event).encode()
    headers = sign_dodo_payload(payload, secret or settings.dodo_webhook_key)
    headers["Content-Type"] = "application/json"
    return await client.post(f"{PREFIX}/webhooks/dodo", content=payload, headers=headers)


def make_subscription_event(event_type: str, **overrides) -> dict:
    """A full, schema-valid Dodo Subscription webhook payload. `overrides`
    patches keys of the nested `data` object (subscription_id, product_id,
    customer, metadata, status, ...)."""
    data = {
        "payload_type": "Subscription",
        "subscription_id": "sub_1",
        "product_id": "pdt_pro",
        "customer": {"customer_id": "cus_1", "email": "owner@acme.example.com", "name": "Owner"},
        "metadata": {},
        "status": "active",
        "currency": "USD",
        "quantity": 1,
        "recurring_pre_tax_amount": 1000,
        "payment_frequency_count": 1,
        "payment_frequency_interval": "Month",
        "subscription_period_count": 1,
        "subscription_period_interval": "Month",
        "tax_inclusive": True,
        "trial_period_days": 0,
        "on_demand": False,
        "cancel_at_next_billing_date": False,
        "created_at": "2026-07-31T10:00:00Z",
        "next_billing_date": "2026-08-31T10:00:00Z",
        "previous_billing_date": "2026-07-31T10:00:00Z",
        "billing": {"city": "x", "country": "US", "state": "x", "street": "x", "zipcode": "x"},
        "brand_id": "brd_1",
        "addons": [],
        "credit_entitlement_cart": [],
        "meter_credit_entitlement_cart": [],
        "meters": [],
    }
    data.update(overrides)
    return {
        "business_id": "biz_1",
        "type": event_type,
        "timestamp": "2026-07-31T10:00:00Z",
        "data": data,
    }


async def _admin_tokens(client, db_session) -> dict:
    owner = await register(client)
    tenant_id = (
        await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    ).tenant_id
    db_session.add(
        User(
            tenant_id=tenant_id,
            email="admin@acme.example.com",
            hashed_password=hash_password(PASSWORD),
            role=UserRole.ADMIN,
        )
    )
    await db_session.flush()
    response = await client.post(
        f"{PREFIX}/auth/login", json={"email": "admin@acme.example.com", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# Checkout session
# --------------------------------------------------------------------------
async def test_checkout_session_happy_path(client, monkeypatch, db_session):
    fake = install_fake_dodo_client(monkeypatch)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(tokens)
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"url": fake._checkout_url}
    assert len(fake.checkout_calls) == 1
    call = fake.checkout_calls[0]
    assert call["product_cart"] == [{"product_id": "pdt_pro", "quantity": 1}]
    assert call["return_url"].startswith(settings.dashboard_base_url)
    assert call["customer"] == {"email": "owner@acme.example.com", "name": "Ada Lovelace"}

    tenant = await db_session.scalar(select(Tenant))
    assert call["metadata"] == {"tenant_id": str(tenant.id)}


async def test_checkout_session_reuses_existing_dodo_customer(client, monkeypatch, db_session):
    fake = install_fake_dodo_client(monkeypatch)
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.dodo_customer_id = "cus_existing"
    await db_session.commit()

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "starter"}, headers=bearer(tokens)
    )

    assert response.status_code == 200, response.text
    assert fake.checkout_calls[0]["customer"] == {"customer_id": "cus_existing"}


async def test_checkout_session_rejects_a_non_paid_plan(client, monkeypatch):
    install_fake_dodo_client(monkeypatch)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "free"}, headers=bearer(tokens)
    )

    assert response.status_code == 422


async def test_checkout_session_requires_owner(client, monkeypatch, db_session):
    install_fake_dodo_client(monkeypatch)
    admin = await _admin_tokens(client, db_session)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(admin)
    )

    assert response.status_code == 403


async def test_checkout_session_without_dodo_configured(client, monkeypatch):
    install_fake_dodo_client(monkeypatch)
    monkeypatch.setattr(settings, "dodo_api_key", None)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(tokens)
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "billing_unavailable"


async def test_checkout_session_without_a_product_id_configured(client, monkeypatch):
    install_fake_dodo_client(monkeypatch)
    monkeypatch.setattr(settings, "dodo_product_id_pro", None)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(tokens)
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "billing_unavailable"


# --------------------------------------------------------------------------
# Portal session
# --------------------------------------------------------------------------
async def test_portal_session_happy_path(client, monkeypatch, db_session):
    fake = install_fake_dodo_client(monkeypatch)
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.dodo_customer_id = "cus_existing"
    await db_session.commit()

    response = await client.post(f"{PREFIX}/billing/portal-session", headers=bearer(tokens))

    assert response.status_code == 200, response.text
    assert response.json() == {"url": fake._portal_url}
    assert fake.portal_calls[0]["customer_id"] == "cus_existing"
    assert fake.portal_calls[0]["return_url"] == f"{settings.dashboard_base_url}/billing"


async def test_portal_session_without_a_dodo_customer(client, monkeypatch):
    install_fake_dodo_client(monkeypatch)
    tokens = await register(client)

    response = await client.post(f"{PREFIX}/billing/portal-session", headers=bearer(tokens))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "billing_unavailable"


async def test_portal_session_requires_owner(client, monkeypatch, db_session):
    install_fake_dodo_client(monkeypatch)
    admin = await _admin_tokens(client, db_session)

    response = await client.post(f"{PREFIX}/billing/portal-session", headers=bearer(admin))

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------
async def test_webhook_bad_signature_is_rejected(client):
    event = make_subscription_event("subscription.active")
    response = await post_webhook(
        client, event, secret="whsec_" + base64.b64encode(b"1" * 24).decode()
    )

    assert response.status_code == 400


async def test_webhook_unhandled_event_type_is_a_noop_200(client):
    event = make_subscription_event("subscription.updated")
    response = await post_webhook(client, event)

    assert response.status_code == 200


async def test_webhook_subscription_active_sets_customer_plan_and_quota(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    assert tenant.dodo_customer_id is None

    event = make_subscription_event(
        "subscription.active",
        subscription_id="sub_1",
        product_id="pdt_pro",
        customer={"customer_id": "cus_new", "email": "owner@acme.example.com", "name": "Owner"},
        metadata={"tenant_id": str(tenant.id)},
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.dodo_customer_id == "cus_new"
    assert tenant.plan == PlanTier.PRO
    assert tenant.monthly_message_quota == billing.PLAN_QUOTAS[PlanTier.PRO]
    assert tenant.dodo_subscription_id == "sub_1"


async def test_webhook_subscription_active_for_unknown_tenant_is_still_200(client):
    event = make_subscription_event(
        "subscription.active", metadata={"tenant_id": "00000000-0000-0000-0000-000000000000"}
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200


async def test_webhook_subscription_active_with_unrecognised_product_leaves_plan_unchanged(
    client, db_session
):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    original_plan = tenant.plan

    event = make_subscription_event(
        "subscription.active",
        product_id="pdt_does_not_exist",
        metadata={"tenant_id": str(tenant.id)},
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == original_plan


async def test_webhook_subscription_renewed_resets_usage_period(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.dodo_customer_id = "cus_1"
    tenant.messages_used_in_period = 999
    await db_session.commit()

    event = make_subscription_event(
        "subscription.renewed",
        customer={"customer_id": "cus_1", "email": "owner@acme.example.com", "name": "Owner"},
        metadata={"tenant_id": str(tenant.id)},
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.messages_used_in_period == 0


async def test_webhook_subscription_renewed_falls_back_to_customer_id_lookup(client, db_session):
    """metadata can in principle be absent on an event; dodo_customer_id is
    the belt-and-suspenders fallback, mirroring the old Stripe dual lookup."""
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.dodo_customer_id = "cus_1"
    tenant.messages_used_in_period = 999
    await db_session.commit()

    event = make_subscription_event(
        "subscription.renewed",
        customer={"customer_id": "cus_1", "email": "owner@acme.example.com", "name": "Owner"},
        metadata={},
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.messages_used_in_period == 0


async def test_webhook_subscription_cancelled_downgrades_to_free(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.dodo_customer_id = "cus_1"
    tenant.plan = PlanTier.PRO
    tenant.monthly_message_quota = 50_000
    tenant.dodo_subscription_id = "sub_1"
    await db_session.commit()

    event = make_subscription_event(
        "subscription.cancelled",
        customer={"customer_id": "cus_1", "email": "owner@acme.example.com", "name": "Owner"},
        metadata={"tenant_id": str(tenant.id)},
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == PlanTier.FREE
    assert tenant.monthly_message_quota == billing.PLAN_QUOTAS[PlanTier.FREE]
    assert tenant.dodo_subscription_id is None
    # The Dodo Customer itself is kept for a possible resubscribe.
    assert tenant.dodo_customer_id == "cus_1"


async def test_webhook_subscription_expired_downgrades_to_free(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.dodo_customer_id = "cus_1"
    tenant.plan = PlanTier.STARTER
    tenant.monthly_message_quota = 10_000
    tenant.dodo_subscription_id = "sub_1"
    await db_session.commit()

    event = make_subscription_event(
        "subscription.expired",
        customer={"customer_id": "cus_1", "email": "owner@acme.example.com", "name": "Owner"},
        metadata={"tenant_id": str(tenant.id)},
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == PlanTier.FREE
