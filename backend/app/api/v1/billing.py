"""Owner-only billing actions: Stripe Checkout and Customer Portal links."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import DbSession, RequireOwner, TenantId
from app.core.errors import AppError, NotFoundError
from app.models import Tenant
from app.models.enums import PlanTier
from app.schemas.billing import CheckoutSessionRequest, CheckoutSessionResponse, PortalSessionResponse
from app.services import billing as billing_service

router = APIRouter()


async def _get_tenant(db: DbSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFoundError("Workspace not found.")
    return tenant


@router.post(
    "/checkout-session",
    response_model=CheckoutSessionResponse,
    summary="Start a Stripe Checkout session to upgrade to a paid plan",
)
async def create_checkout_session(
    payload: CheckoutSessionRequest, db: DbSession, tenant_id: TenantId, _: RequireOwner
) -> CheckoutSessionResponse:
    tenant = await _get_tenant(db, tenant_id)
    try:
        url = await billing_service.create_checkout_session(tenant, PlanTier(payload.plan))
    except billing_service.BillingUnavailableError as exc:
        raise AppError(
            str(exc), code="billing_unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc
    return CheckoutSessionResponse(url=url)


@router.post(
    "/portal-session",
    response_model=PortalSessionResponse,
    summary="Get a Stripe Customer Portal link (cancel, downgrade, payment method)",
)
async def create_portal_session(
    db: DbSession, tenant_id: TenantId, _: RequireOwner
) -> PortalSessionResponse:
    tenant = await _get_tenant(db, tenant_id)
    try:
        url = await billing_service.create_portal_session(tenant)
    except billing_service.BillingUnavailableError as exc:
        raise AppError(
            str(exc), code="billing_unavailable", status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc
    return PortalSessionResponse(url=url)
