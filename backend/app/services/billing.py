"""Stripe billing: Checkout, Customer Portal, and webhook-driven state sync.

No client-object seam like llm.get_anthropic_client/voice.get_openai_client:
stripe-python's async resource methods (`create_async`) accept `api_key` as a
per-call argument, so there is no global client to construct or monkeypatch —
tests instead monkeypatch the resource methods themselves
(`stripe.checkout.Session.create_async`, etc.), which is stripe-python's own
documented seam for this style of call.

The webhook-side state mutators (record_checkout_completion,
apply_subscription_state, reset_usage_period, downgrade_to_free) don't take a
db session or commit anything — they only mutate an already-session-attached
Tenant, and app.db.session.get_db commits at the end of the request. That's
the default for this codebase; only app/services/chat.py deviates, and only
because it must survive a subsequent step (the Claude call) that can fail.
Nothing after these runs in the webhook handler, so there's nothing to
protect against here.
"""

from __future__ import annotations

import logging
from datetime import datetime

import stripe

from app.core.config import settings
from app.models import Tenant
from app.models.enums import PlanTier

logger = logging.getLogger(__name__)

# Product decision, not deployment config — adjust here when pricing changes.
PLAN_QUOTAS: dict[PlanTier, int] = {
    PlanTier.FREE: 1_000,
    PlanTier.STARTER: 10_000,
    PlanTier.PRO: 50_000,
    PlanTier.ENTERPRISE: 500_000,
}

# Which settings field holds each paid plan's Stripe Price ID. FREE is
# deliberately absent — you can't check out into free, only cancel into it.
_PLAN_PRICE_SETTINGS: dict[PlanTier, str] = {
    PlanTier.STARTER: "stripe_price_id_starter",
    PlanTier.PRO: "stripe_price_id_pro",
    PlanTier.ENTERPRISE: "stripe_price_id_enterprise",
}


class BillingUnavailableError(Exception):
    """Stripe isn't configured (no secret key), a paid plan has no Price ID
    configured, or the requested action needs billing history that doesn't
    exist yet (e.g. a portal session for a tenant that never checked out)."""


def _require_secret_key() -> str:
    if not settings.stripe_secret_key:
        raise BillingUnavailableError("STRIPE_SECRET_KEY is not configured.")
    return settings.stripe_secret_key


def price_id_for_plan(plan: PlanTier) -> str:
    if plan not in _PLAN_PRICE_SETTINGS:
        raise BillingUnavailableError(f"{plan.value} has no Stripe price — it isn't a paid plan.")
    price_id = getattr(settings, _PLAN_PRICE_SETTINGS[plan])
    if not price_id:
        raise BillingUnavailableError(f"No Stripe price ID is configured for the {plan.value} plan.")
    return price_id


def plan_for_price_id(price_id: str) -> PlanTier | None:
    """Reverse lookup — None for a price ID that doesn't match any of this
    app's configured tiers (e.g. a Price created for something else in the
    same Stripe account)."""
    for plan, setting_name in _PLAN_PRICE_SETTINGS.items():
        if getattr(settings, setting_name) == price_id:
            return plan
    return None


async def create_checkout_session(tenant: Tenant, plan: PlanTier) -> str:
    api_key = _require_secret_key()
    price_id = price_id_for_plan(plan)

    params: dict = dict(
        api_key=api_key,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        # Belt-and-suspenders: whichever webhook event arrives first,
        # client_reference_id and metadata both independently identify the
        # tenant, so neither being unexpectedly absent loses the mapping.
        client_reference_id=str(tenant.id),
        metadata={"tenant_id": str(tenant.id)},
        success_url=f"{settings.dashboard_base_url}/billing?checkout=success",
        cancel_url=f"{settings.dashboard_base_url}/billing?checkout=cancelled",
    )
    # Reuse the existing Stripe Customer if this tenant has one (a returning
    # customer after a prior cancellation) — omitting the key entirely (not
    # passing customer=None) lets Stripe create a fresh Customer otherwise.
    if tenant.stripe_customer_id:
        params["customer"] = tenant.stripe_customer_id

    session = await stripe.checkout.Session.create_async(**params)
    return session.url


async def create_portal_session(tenant: Tenant) -> str:
    api_key = _require_secret_key()
    if not tenant.stripe_customer_id:
        raise BillingUnavailableError("This workspace has no billing history yet.")

    session = await stripe.billing_portal.Session.create_async(
        api_key=api_key,
        customer=tenant.stripe_customer_id,
        return_url=f"{settings.dashboard_base_url}/billing",
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """Raises stripe.SignatureVerificationError on a bad/forged signature —
    callers map that to a 400, same as any other malformed request."""
    if not settings.stripe_webhook_secret:
        raise BillingUnavailableError("STRIPE_WEBHOOK_SECRET is not configured.")
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def record_checkout_completion(tenant: Tenant, session: stripe.checkout.Session) -> None:
    tenant.stripe_customer_id = session.customer


def apply_subscription_state(tenant: Tenant, subscription: stripe.Subscription) -> None:
    """Syncs plan/quota/subscription id from a Subscription's price.

    Deliberately does not touch messages_used_in_period/period_started_at —
    see reset_usage_period. A subscription can update for reasons unrelated
    to a billing-cycle renewal (e.g. a metadata change), and those shouldn't
    reset anyone's usage counter.

    NOTE: StripeObject subclasses dict, so `subscription["items"]` (not
    `subscription.items`, which resolves to dict.items the method) is the
    only correct way to reach the "items" field.
    """
    price_id = subscription["items"]["data"][0]["price"]["id"]
    plan = plan_for_price_id(price_id)
    if plan is None:
        logger.warning(
            "subscription %s has an unrecognised price %s — leaving tenant %s's plan unchanged",
            subscription.id,
            price_id,
            tenant.id,
        )
        return
    tenant.plan = plan
    tenant.monthly_message_quota = PLAN_QUOTAS[plan]
    tenant.stripe_subscription_id = subscription.id


def reset_usage_period(tenant: Tenant, period_start: datetime) -> None:
    tenant.messages_used_in_period = 0
    tenant.period_started_at = period_start


def downgrade_to_free(tenant: Tenant) -> None:
    """A cancelled subscription reverts to the free tier — it does not
    deactivate the tenant (Tenant.is_active is a separate, harsher concept)."""
    tenant.plan = PlanTier.FREE
    tenant.monthly_message_quota = PLAN_QUOTAS[PlanTier.FREE]
    tenant.stripe_subscription_id = None
