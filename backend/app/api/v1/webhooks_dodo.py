"""Dodo Payments webhook endpoint.

Not part of the dashboard OR public-widget auth models — Dodo calls this
server-to-server with no Authorization header and no browser Origin at all.
The only authentication is the signature check against the raw request body,
which is why this reads `await request.body()` directly instead of taking a
parsed Pydantic model: FastAPI's JSON parsing would already have consumed/
reformatted the body, and signature verification requires the exact bytes
Dodo sent.

Tenant resolution is simpler here than the old Stripe version: Dodo's
Subscription object carries `metadata` as one of its own fields, present on
every subscription event (not just a one-off checkout payload the way
Stripe's Session object was) — so one metadata lookup covers every event
type below, with a dodo_customer_id fallback for defensiveness.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select
from standardwebhooks.webhooks import WebhookVerificationError

from app.api.deps import DbSession
from app.models import Tenant
from app.services import billing as billing_service

logger = logging.getLogger(__name__)
router = APIRouter()

# Event types this handler acts on; everything else (subscription.on_hold,
# subscription.failed, subscription.updated, payment.*, etc.) is acknowledged
# and ignored — Dodo's own guidance, like Stripe's, is to 200 events you
# don't act on, not to reject them.
_ACTIVATION_EVENTS = {"subscription.active"}
_RENEWAL_EVENTS = {"subscription.renewed"}
_DOWNGRADE_EVENTS = {"subscription.cancelled", "subscription.expired"}


async def _find_tenant(db: DbSession, subscription) -> Tenant | None:
    tenant_id_str = subscription.metadata.get("tenant_id") if subscription.metadata else None
    if tenant_id_str:
        try:
            tenant = await db.get(Tenant, uuid.UUID(str(tenant_id_str)))
        except ValueError:
            tenant = None
        if tenant is not None:
            return tenant

    customer_id = subscription.customer.customer_id if subscription.customer else None
    if customer_id:
        return await db.scalar(select(Tenant).where(Tenant.dodo_customer_id == customer_id))
    return None


@router.post("/dodo", include_in_schema=False, summary="Dodo Payments webhook endpoint")
async def dodo_webhook(request: Request, db: DbSession) -> Response:
    payload = await request.body()
    headers = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
    }

    try:
        event = billing_service.construct_webhook_event(payload, headers)
    except billing_service.BillingUnavailableError:
        logger.error("Dodo webhook received but DODO_WEBHOOK_KEY is not configured")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    except WebhookVerificationError:
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    subscription = event.data

    if event.type in _ACTIVATION_EVENTS:
        tenant = await _find_tenant(db, subscription)
        if tenant is not None:
            billing_service.apply_subscription_state(tenant, subscription)

    elif event.type in _RENEWAL_EVENTS:
        tenant = await _find_tenant(db, subscription)
        if tenant is not None:
            billing_service.reset_usage_period(tenant, datetime.now(timezone.utc))

    elif event.type in _DOWNGRADE_EVENTS:
        tenant = await _find_tenant(db, subscription)
        if tenant is not None:
            billing_service.downgrade_to_free(tenant)

    return Response(status_code=status.HTTP_200_OK)
