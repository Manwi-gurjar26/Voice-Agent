from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import DbSession, client_ip
from app.api.public_deps import PublicAgent, WidgetSessionDep, enforce_public_rate_limit
from app.schemas.public import AgentPublicConfig, WidgetSessionInfo, WidgetSessionResponse
from app.services import widget_sessions as session_service

router = APIRouter()

RateLimited = Annotated[None, Depends(enforce_public_rate_limit)]

_PREFLIGHT_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Max-Age": "600",
}


@router.get(
    "/agents/{public_key}/config",
    response_model=AgentPublicConfig,
    summary="Public widget bootstrap config",
)
async def get_public_config(agent: PublicAgent, _rl: RateLimited) -> AgentPublicConfig:
    return AgentPublicConfig.model_validate(agent)


@router.post(
    "/agents/{public_key}/sessions",
    response_model=WidgetSessionResponse,
    summary="Start a widget session",
)
async def create_session(
    agent: PublicAgent,
    _rl: RateLimited,
    db: DbSession,
    request: Request,
    ip: Annotated[str | None, Depends(client_ip)],
) -> WidgetSessionResponse:
    # request.state.cors_origin was set by resolve_public_agent (the PublicAgent
    # dependency) after validating this same Origin header against the agent's
    # allowlist — reusing it here avoids re-normalising it a second time.
    return await session_service.create_widget_session(
        db,
        agent,
        origin=request.state.cors_origin,
        user_agent=request.headers.get("User-Agent"),
        ip_address=ip,
    )


@router.get(
    "/sessions/me",
    response_model=WidgetSessionInfo,
    summary="Validate a widget session token",
)
async def session_me(session: WidgetSessionDep) -> WidgetSessionInfo:
    return WidgetSessionInfo.model_validate(session)


# --------------------------------------------------------------------------
# CORS preflight
#
# Browsers preflight any cross-origin request carrying a JSON body or an
# Authorization header, so every route above needs an OPTIONS counterpart.
# These run through the *same* dependencies as the real routes (not a
# bespoke check in middleware) so preflight enforcement is guaranteed to
# match the real request byte-for-byte — see PublicWidgetCorsMiddleware's
# docstring for why that matters.
# --------------------------------------------------------------------------
@router.options("/agents/{public_key}/config", include_in_schema=False)
@router.options("/agents/{public_key}/sessions", include_in_schema=False)
async def preflight_for_agent_route(agent: PublicAgent) -> Response:
    """resolve_public_agent has already validated the origin and, on success,
    left request.state.cors_origin set for the middleware to copy onto this
    response. A rejected origin or unknown agent raises the same 404/403 the
    real routes would — with no CORS header attached, which is what makes a
    browser refuse to send the real request for a disallowed origin."""
    return Response(status_code=204, headers=_PREFLIGHT_HEADERS)


@router.options("/sessions/me", include_in_schema=False)
async def preflight_for_sessions_me() -> Response:
    """No {public_key} in this path, so there's no agent to check before the
    real request exists — see PublicWidgetCorsMiddleware's docstring. The
    middleware reflects the Origin permissively here; real enforcement is
    get_widget_session's origin re-check on the actual GET."""
    return Response(status_code=204, headers=_PREFLIGHT_HEADERS)
