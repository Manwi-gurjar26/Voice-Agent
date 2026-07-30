from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
import stripe
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
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_fake")
    monkeypatch.setattr(settings, "stripe_price_id_starter", "price_starter")
    monkeypatch.setattr(settings, "stripe_price_id_pro", "price_pro")
    monkeypatch.setattr(settings, "stripe_price_id_enterprise", "price_enterprise")


# --------------------------------------------------------------------------
# Fake Stripe resource methods — the seam is the resource classmethods
# themselves (stripe.checkout.Session.create_async, etc.), since
# stripe-python's async calls take api_key per-call rather than through a
# constructed client object. See app/services/billing.py's module docstring.
# --------------------------------------------------------------------------
class _FakeSession:
    def __init__(self, url: str) -> None:
        self.url = url


def install_fake_checkout(monkeypatch, url: str = "https://checkout.stripe.com/test-session"):
    calls: list[dict] = []

    async def _fake_create(**kwargs):
        calls.append(kwargs)
        return _FakeSession(url)

    monkeypatch.setattr(stripe.checkout.Session, "create_async", _fake_create)
    return calls


def install_fake_portal(monkeypatch, url: str = "https://billing.stripe.com/test-portal"):
    calls: list[dict] = []

    async def _fake_create(**kwargs):
        calls.append(kwargs)
        return _FakeSession(url)

    monkeypatch.setattr(stripe.billing_portal.Session, "create_async", _fake_create)
    return calls


def sign_payload(payload: bytes, secret: str) -> str:
    """Replicates stripe.WebhookSignature._compute_signature exactly, so
    webhook tests exercise the real stripe.Webhook.construct_event path
    rather than a mocked one."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload.decode()}"
    signature = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={signature}"


async def post_webhook(client, event: dict, secret: str | None = None):
    payload = json.dumps(event).encode()
    sig = sign_payload(payload, secret or settings.stripe_webhook_secret)
    return await client.post(
        f"{PREFIX}/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )


def make_event(event_type: str, obj: dict) -> dict:
    return {"id": "evt_test", "object": "event", "type": event_type, "data": {"object": obj}}


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
    calls = install_fake_checkout(monkeypatch)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(tokens)
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://checkout.stripe.com/test-session"}
    assert len(calls) == 1
    assert calls[0]["line_items"] == [{"price": "price_pro", "quantity": 1}]
    assert calls[0]["mode"] == "subscription"
    assert calls[0]["success_url"].startswith(settings.dashboard_base_url)
    assert "customer" not in calls[0]

    tenant = await db_session.scalar(select(Tenant))
    assert calls[0]["client_reference_id"] == str(tenant.id)
    assert calls[0]["metadata"] == {"tenant_id": str(tenant.id)}


async def test_checkout_session_reuses_existing_stripe_customer(client, monkeypatch, db_session):
    calls = install_fake_checkout(monkeypatch)
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_customer_id = "cus_existing"
    await db_session.commit()

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "starter"}, headers=bearer(tokens)
    )

    assert response.status_code == 200, response.text
    assert calls[0]["customer"] == "cus_existing"


async def test_checkout_session_rejects_a_non_paid_plan(client, monkeypatch):
    install_fake_checkout(monkeypatch)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "free"}, headers=bearer(tokens)
    )

    assert response.status_code == 422


async def test_checkout_session_requires_owner(client, monkeypatch, db_session):
    install_fake_checkout(monkeypatch)
    admin = await _admin_tokens(client, db_session)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(admin)
    )

    assert response.status_code == 403


async def test_checkout_session_without_stripe_configured(client, monkeypatch):
    install_fake_checkout(monkeypatch)
    monkeypatch.setattr(settings, "stripe_secret_key", None)
    tokens = await register(client)

    response = await client.post(
        f"{PREFIX}/billing/checkout-session", json={"plan": "pro"}, headers=bearer(tokens)
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "billing_unavailable"


async def test_checkout_session_without_a_price_id_configured(client, monkeypatch):
    install_fake_checkout(monkeypatch)
    monkeypatch.setattr(settings, "stripe_price_id_pro", None)
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
    calls = install_fake_portal(monkeypatch)
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_customer_id = "cus_existing"
    await db_session.commit()

    response = await client.post(f"{PREFIX}/billing/portal-session", headers=bearer(tokens))

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://billing.stripe.com/test-portal"}
    assert calls[0]["customer"] == "cus_existing"
    assert calls[0]["return_url"] == f"{settings.dashboard_base_url}/billing"


async def test_portal_session_without_a_stripe_customer(client, monkeypatch):
    install_fake_portal(monkeypatch)
    tokens = await register(client)

    response = await client.post(f"{PREFIX}/billing/portal-session", headers=bearer(tokens))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "billing_unavailable"


async def test_portal_session_requires_owner(client, monkeypatch, db_session):
    install_fake_portal(monkeypatch)
    admin = await _admin_tokens(client, db_session)

    response = await client.post(f"{PREFIX}/billing/portal-session", headers=bearer(admin))

    assert response.status_code == 403


# --------------------------------------------------------------------------
# Webhook
# --------------------------------------------------------------------------
async def test_webhook_bad_signature_is_rejected(client):
    event = make_event("checkout.session.completed", {"id": "cs_1", "object": "checkout.session"})
    response = await post_webhook(client, event, secret="wrong_secret")

    assert response.status_code == 400


async def test_webhook_unhandled_event_type_is_a_noop_200(client):
    event = make_event("customer.updated", {"id": "cus_1", "object": "customer"})
    response = await post_webhook(client, event)

    assert response.status_code == 200


async def test_webhook_checkout_completed_sets_stripe_customer_id(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    assert tenant.stripe_customer_id is None

    event = make_event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "object": "checkout.session",
            "customer": "cus_new",
            "client_reference_id": str(tenant.id),
            "metadata": {"tenant_id": str(tenant.id)},
        },
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.stripe_customer_id == "cus_new"


async def test_webhook_checkout_completed_for_unknown_tenant_is_still_200(client):
    event = make_event(
        "checkout.session.completed",
        {
            "id": "cs_1",
            "object": "checkout.session",
            "customer": "cus_new",
            "client_reference_id": "00000000-0000-0000-0000-000000000000",
            "metadata": {},
        },
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200


def _subscription_object(customer: str, price_id: str, sub_id: str = "sub_1") -> dict:
    return {
        "id": sub_id,
        "object": "subscription",
        "customer": customer,
        "items": {
            "object": "list",
            "data": [{"price": {"id": price_id, "object": "price"}}],
        },
    }


async def test_webhook_subscription_created_sets_plan_and_quota(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_customer_id = "cus_1"
    await db_session.commit()

    event = make_event(
        "customer.subscription.created", _subscription_object("cus_1", "price_pro")
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == PlanTier.PRO
    assert tenant.monthly_message_quota == billing.PLAN_QUOTAS[PlanTier.PRO]
    assert tenant.stripe_subscription_id == "sub_1"


async def test_webhook_subscription_updated_does_not_touch_usage_counters(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_customer_id = "cus_1"
    tenant.messages_used_in_period = 42
    await db_session.commit()

    event = make_event(
        "customer.subscription.updated", _subscription_object("cus_1", "price_starter")
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == PlanTier.STARTER
    assert tenant.messages_used_in_period == 42


async def test_webhook_subscription_with_unrecognised_price_leaves_plan_unchanged(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_customer_id = "cus_1"
    original_plan = tenant.plan
    await db_session.commit()

    event = make_event(
        "customer.subscription.created", _subscription_object("cus_1", "price_does_not_exist")
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == original_plan


async def test_webhook_subscription_deleted_downgrades_to_free(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_customer_id = "cus_1"
    tenant.plan = PlanTier.PRO
    tenant.monthly_message_quota = 50_000
    tenant.stripe_subscription_id = "sub_1"
    await db_session.commit()

    event = make_event(
        "customer.subscription.deleted", _subscription_object("cus_1", "price_pro")
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.plan == PlanTier.FREE
    assert tenant.monthly_message_quota == billing.PLAN_QUOTAS[PlanTier.FREE]
    assert tenant.stripe_subscription_id is None
    # The Stripe Customer itself is kept for a possible resubscribe.
    assert tenant.stripe_customer_id == "cus_1"


async def test_webhook_invoice_paid_resets_usage_period(client, db_session):
    tokens = await register(client)
    tenant = await db_session.scalar(select(Tenant))
    tenant.stripe_subscription_id = "sub_1"
    tenant.messages_used_in_period = 999
    await db_session.commit()

    event = make_event(
        "invoice.paid", {"id": "in_1", "object": "invoice", "subscription": "sub_1"}
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
    await db_session.refresh(tenant)
    assert tenant.messages_used_in_period == 0


async def test_webhook_invoice_paid_for_unknown_subscription_is_still_200(client):
    event = make_event(
        "invoice.paid", {"id": "in_1", "object": "invoice", "subscription": "sub_unknown"}
    )
    response = await post_webhook(client, event)

    assert response.status_code == 200
