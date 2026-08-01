"""Aggregates every v1 route. New routers get registered here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import agents, auth, billing, documents, health, public, public_chat, webhooks_dodo

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(
    documents.router, prefix="/agents/{agent_id}/documents", tags=["documents"]
)
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(webhooks_dodo.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(public.router, prefix="/public", tags=["public"])
api_router.include_router(public_chat.router, prefix="/public", tags=["public"])
