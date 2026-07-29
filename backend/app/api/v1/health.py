from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: Literal["up", "down"]


@router.get("/health", response_model=LivenessResponse, summary="Liveness probe")
async def health() -> LivenessResponse:
    """Process is up. Deliberately touches no dependencies — a failing database
    must not cause an orchestrator to kill an otherwise healthy container."""
    return LivenessResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReadinessResponse:
    """Dependencies are reachable, so this instance can serve traffic."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any failure means "not ready"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", database="down")
    return ReadinessResponse(status="ready", database="up")
