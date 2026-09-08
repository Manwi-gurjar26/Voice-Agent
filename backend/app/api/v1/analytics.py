from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DbSession, TenantId
from app.schemas.analytics import AnalyticsOverview
from app.services import analytics as analytics_service

router = APIRouter()


@router.get(
    "/overview",
    response_model=AnalyticsOverview,
    summary="Workspace activity, usage, and knowledge-base health",
)
async def get_overview(
    db: DbSession,
    tenant_id: TenantId,
    # Capped at 90: the window is scanned live off the messages table with no
    # rollup behind it, and the dashboard has no UI for anything longer.
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> AnalyticsOverview:
    """Read-only, and available to every role including `member` — this
    aggregates activity the whole workspace shares, and exposes no
    configuration a member cannot already read from GET /agents."""
    return await analytics_service.overview(db, tenant_id, days=days)
