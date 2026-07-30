"""Stripe webhook endpoint.

Not part of the dashboard OR public-widget auth models — Stripe calls this
server-to-server with no Authorization header and no browser Origin at all.
The only authentication is the signature check against the raw request body,
which is why this reads `await request.body()` directly instead of taking a
parsed Pydantic model: FastAPI's JSON parsing would already have consumed/
reformatted the body, and signature verification requires the exact bytes
Stripe sent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.models import Tenant
from app.services import billing as billing_service

logger = logging.getLogger(__name__)
router = APIRouter()


async def _find_tenant_by_customer(db: DbSession, customer_id: str | None) -> Tenant | None:
    if not customer_id:
        return None
    return await db.scalar(select(Tenant).where(Tenant.stripe_customer_id == customer_id))


async def _find_tenant_by_subscription(db: DbSession, subscription_id: str | None) -> Tenant | None:
    if not subscription_id:
        return None
    return await db.scalar(select(Tenant).where(Tenant.stripe_subscription_id == subscription_id))


async def _resolve_checkout_tenant(db: DbSession, session: stripe.checkout.Session) -> Tenant | None:
    tenant_id_str = session.client_reference_id or (session.metadata or {}).get("tenant_id")
    if not tenant_id_str:
        return None
    try:
        tenant_id = uuid.UUID(tenant_id_str)
    except ValueError:
        return None
    return await db.get(Tenant, tenant_id)


@router.post("/stripe", include_in_schema=False, summary="Stripe webhook endpoint")
async def stripe_webhook(request: Request, db: DbSession) -> Response:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = billing_service.construct_webhook_event(payload, sig_header)
    except billing_service.BillingUnavailableError:
        logger.error("Stripe webhook received but STRIPE_WEBHOOK_SECRET is not configured")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except stripe.SignatureVerificationError:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    obj = event.data.object

    if event.type == "checkout.session.completed":
        tenant = await _resolve_checkout_tenant(db, obj)
        if tenant is not None:
            billing_service.record_checkout_completion(tenant, obj)

    elif event.type in ("customer.subscription.created", "customer.subscription.updated"):
        tenant = await _find_tenant_by_customer(db, obj.customer)
        if tenant is not None:
            billing_service.apply_subscription_state(tenant, obj)

    elif event.type == "customer.subscription.deleted":
        tenant = await _find_tenant_by_customer(db, obj.customer)
        if tenant is not None:
            billing_service.downgrade_to_free(tenant)

    elif event.type == "invoice.paid":
        tenant = await _find_tenant_by_subscription(db, obj.get("subscription"))
        if tenant is not None:
            billing_service.reset_usage_period(tenant, datetime.now(timezone.utc))

    # Every other event type is acknowledged and ignored — Stripe's own
    # guidance is to 200 events you don't act on, not to reject them.
    return Response(status_code=status.HTTP_200_OK)
