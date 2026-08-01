"""Dodo Payments billing: Checkout, Customer Portal, and webhook-driven state sync.

Originally built against Stripe; swapped to Dodo Payments (a merchant-of-
record gateway) because Stripe does not onboard new India-registered
accounts — a hard block for an India-based merchant trying to verify this
step at all, not a preference. Dodo's test mode is free and unlimited, same
as Stripe's, and its Python SDK is a real client object (`AsyncDodoPayments`)
rather than Stripe-python's per-call `api_key` argument style — so, unlike
the old Stripe code, this module *does* have a single mockable client seam
(`get_dodo_client`), matching the pattern already used for Anthropic/OpenAI
in `llm.py`/`voice.py`.

The webhook-side state mutators (apply_subscription_state, reset_usage_period,
downgrade_to_free) don't take a db session or commit anything — they only
mutate an already-session-attached Tenant, and app.db.session.get_db commits
at the end of the request. That's the default for this codebase; only
app/services/chat.py deviates, and only because it must survive a subsequent
step (the Claude call) that can fail. Nothing after these runs in the webhook
handler, so there's nothing to protect against here.

A real simplification over the Stripe version, found while integrating:
Dodo's Subscription object carries `metadata` as one of its own persisted
fields, present on *every* subscription webhook (creation, renewal,
cancellation — not just a one-time checkout-session payload the way Stripe's
Session object was). So there's no need for Stripe's separate
"resolve tenant from the checkout session" vs. "resolve tenant from the
subscription's customer id" split — one metadata-based lookup, with a
customer-id fallback, covers every event type here.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Mapping

from dodopayments import AsyncDodoPayments
from dodopayments.types.attach_existing_customer_param import AttachExistingCustomerParam
from dodopayments.types.new_customer_param import NewCustomerParam
from dodopayments.types.subscription import Subscription

from app.core.config import settings
from app.models import Tenant, User
from app.models.enums import PlanTier

logger = logging.getLogger(__name__)

# Product decision, not deployment config — adjust here when pricing changes.
PLAN_QUOTAS: dict[PlanTier, int] = {
    PlanTier.FREE: 1_000,
    PlanTier.STARTER: 10_000,
    PlanTier.PRO: 50_000,
    PlanTier.ENTERPRISE: 500_000,
}

# Which settings field holds each paid plan's Dodo Product ID. FREE is
# deliberately absent — you can't check out into free, only cancel into it.
_PLAN_PRODUCT_SETTINGS: dict[PlanTier, str] = {
    PlanTier.STARTER: "dodo_product_id_starter",
    PlanTier.PRO: "dodo_product_id_pro",
    PlanTier.ENTERPRISE: "dodo_product_id_enterprise",
}

_client: AsyncDodoPayments | None = None


def get_dodo_client() -> AsyncDodoPayments:
    global _client
    if _client is None:
        _client = AsyncDodoPayments(
            bearer_token=settings.dodo_api_key or "",
            environment=settings.dodo_environment,
            webhook_key=settings.dodo_webhook_key or "",
        )
    return _client


def _reset_client_for_tests() -> None:
    global _client
    _client = None


class BillingUnavailableError(Exception):
    """Dodo isn't configured (no API key), a paid plan has no Product ID
    configured, or the requested action needs billing history that doesn't
    exist yet (e.g. a portal session for a tenant that never checked out)."""


def _require_api_key() -> None:
    if not settings.dodo_api_key:
        raise BillingUnavailableError("DODO_API_KEY is not configured.")


def product_id_for_plan(plan: PlanTier) -> str:
    if plan not in _PLAN_PRODUCT_SETTINGS:
        raise BillingUnavailableError(f"{plan.value} has no Dodo product — it isn't a paid plan.")
    product_id = getattr(settings, _PLAN_PRODUCT_SETTINGS[plan])
    if not product_id:
        raise BillingUnavailableError(f"No Dodo product ID is configured for the {plan.value} plan.")
    return product_id


def plan_for_product_id(product_id: str) -> PlanTier | None:
    """Reverse lookup — None for a product ID that doesn't match any of this
    app's configured tiers (e.g. a Product created for something else in the
    same Dodo account)."""
    for plan, setting_name in _PLAN_PRODUCT_SETTINGS.items():
        if getattr(settings, setting_name) == product_id:
            return plan
    return None


async def create_checkout_session(tenant: Tenant, plan: PlanTier, owner: User) -> str:
    _require_api_key()
    product_id = product_id_for_plan(plan)
    client = get_dodo_client()

    # Reuse the existing Dodo Customer if this tenant has one (a returning
    # customer after a prior cancellation); otherwise Dodo creates a fresh
    # one from the email/name supplied here. Unlike Stripe, Dodo's checkout
    # session has no separate "leave customer unset and let it collect an
    # email on the page" mode for a *new* customer — one of these two shapes
    # is required.
    customer: AttachExistingCustomerParam | NewCustomerParam
    if tenant.dodo_customer_id:
        customer = AttachExistingCustomerParam(customer_id=tenant.dodo_customer_id)
    else:
        customer = NewCustomerParam(email=owner.email, name=owner.full_name or owner.email)

    session = await client.checkout_sessions.create(
        product_cart=[{"product_id": product_id, "quantity": 1}],
        customer=customer,
        # Belt-and-suspenders would be redundant here — see module docstring:
        # this metadata lands on the Subscription object itself and is present
        # on every subsequent webhook, not just a one-time checkout payload.
        metadata={"tenant_id": str(tenant.id)},
        return_url=f"{settings.dashboard_base_url}/billing?checkout=success",
        cancel_url=f"{settings.dashboard_base_url}/billing?checkout=cancelled",
    )
    return session.checkout_url


async def create_portal_session(tenant: Tenant) -> str:
    _require_api_key()
    if not tenant.dodo_customer_id:
        raise BillingUnavailableError("This workspace has no billing history yet.")

    client = get_dodo_client()
    session = await client.customers.customer_portal.create(
        tenant.dodo_customer_id,
        return_url=f"{settings.dashboard_base_url}/billing",
    )
    return session.link


def construct_webhook_event(payload: bytes, headers: Mapping[str, str]):
    """Raises standardwebhooks.webhooks.WebhookVerificationError on a bad/
    forged signature — callers map that to a 400, same as any other malformed
    request. Verified directly against the real SDK (not assumed): a bad
    `webhook-signature` header raises exactly that exception, confirmed by
    hand-signing a payload and deliberately corrupting the signature before
    calling this."""
    if not settings.dodo_webhook_key:
        raise BillingUnavailableError("DODO_WEBHOOK_KEY is not configured.")
    client = get_dodo_client()
    return client.webhooks.unwrap(payload.decode(), headers=headers)


def apply_subscription_state(tenant: Tenant, subscription: Subscription) -> None:
    """Syncs customer id/plan/quota/subscription id from a Subscription's
    product. Deliberately does not touch messages_used_in_period/
    period_started_at — see reset_usage_period. A subscription can update for
    reasons unrelated to a billing-cycle renewal, and those shouldn't reset
    anyone's usage counter.

    Unlike Stripe's StripeObject (which subclasses dict and shadows
    `.items`), Dodo's Subscription is a plain pydantic model — ordinary
    attribute access throughout, no dict-method-collision gotcha to work
    around."""
    plan = plan_for_product_id(subscription.product_id)
    if plan is None:
        logger.warning(
            "subscription %s has an unrecognised product %s — leaving tenant %s's plan unchanged",
            subscription.subscription_id,
            subscription.product_id,
            tenant.id,
        )
        return
    tenant.dodo_customer_id = subscription.customer.customer_id
    tenant.plan = plan
    tenant.monthly_message_quota = PLAN_QUOTAS[plan]
    tenant.dodo_subscription_id = subscription.subscription_id


def reset_usage_period(tenant: Tenant, period_start: datetime) -> None:
    tenant.messages_used_in_period = 0
    tenant.period_started_at = period_start


def downgrade_to_free(tenant: Tenant) -> None:
    """A cancelled/expired subscription reverts to the free tier — it does
    not deactivate the tenant (Tenant.is_active is a separate, harsher
    concept)."""
    tenant.plan = PlanTier.FREE
    tenant.monthly_message_quota = PLAN_QUOTAS[PlanTier.FREE]
    tenant.dodo_subscription_id = None
