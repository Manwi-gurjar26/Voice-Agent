from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, DbSession, TenantId, require_roles
from app.models.enums import UserRole
from app.schemas.agent import AgentCreate, AgentListResponse, AgentRead, AgentUpdate
from app.services import agents as agent_service

router = APIRouter()

# Members may read agents; changing configuration is owner/admin only.
WriteAccess = Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.ADMIN))]


@router.get("", response_model=AgentListResponse, summary="List agents in the workspace")
async def list_agents(
    db: DbSession,
    tenant_id: TenantId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AgentListResponse:
    items, total = await agent_service.list_agents(db, tenant_id, limit=limit, offset=offset)
    return AgentListResponse(
        items=[AgentRead.model_validate(a) for a in items], total=total
    )


@router.post(
    "",
    response_model=AgentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an agent",
)
async def create_agent(
    payload: AgentCreate, db: DbSession, tenant_id: TenantId, _: WriteAccess
) -> AgentRead:
    agent = await agent_service.create_agent(db, tenant_id, payload)
    return AgentRead.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentRead, summary="Fetch one agent")
async def get_agent(agent_id: uuid.UUID, db: DbSession, tenant_id: TenantId) -> AgentRead:
    agent = await agent_service.get_agent(db, tenant_id, agent_id)
    return AgentRead.model_validate(agent)


@router.patch("/{agent_id}", response_model=AgentRead, summary="Update an agent")
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    db: DbSession,
    tenant_id: TenantId,
    _: WriteAccess,
) -> AgentRead:
    agent = await agent_service.update_agent(db, tenant_id, agent_id, payload)
    return AgentRead.model_validate(agent)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(
    agent_id: uuid.UUID, db: DbSession, tenant_id: TenantId, _: WriteAccess
) -> Response:
    await agent_service.delete_agent(db, tenant_id, agent_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
