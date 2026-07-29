"""Agent CRUD. Every function takes tenant_id and filters on it."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.models import Agent
from app.models.agent import _default_theme
from app.schemas.agent import AgentCreate, AgentUpdate


async def get_agent(db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    """Fetch one agent within a tenant.

    tenant_id is part of the WHERE clause, not an assertion afterwards, so an
    agent belonging to another tenant is indistinguishable from one that does
    not exist — no 403-vs-404 signal that would confirm the id is real.
    """
    agent = await db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id)
    )
    if agent is None:
        raise NotFoundError("Agent not found.")
    return agent


async def list_agents(
    db: AsyncSession, tenant_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> tuple[list[Agent], int]:
    total = await db.scalar(
        select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id)
    )
    rows = await db.scalars(
        select(Agent)
        .where(Agent.tenant_id == tenant_id)
        .order_by(Agent.created_at.desc(), Agent.id)  # id breaks ties deterministically
        .limit(limit)
        .offset(offset)
    )
    return list(rows), int(total or 0)


async def create_agent(db: AsyncSession, tenant_id: uuid.UUID, payload: AgentCreate) -> Agent:
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    data.setdefault("theme", _default_theme())
    data.setdefault("allowed_origins", [])

    agent = Agent(tenant_id=tenant_id, **data)
    db.add(agent)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("An agent with this name already exists.") from exc
    return agent


async def update_agent(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, payload: AgentUpdate
) -> Agent:
    agent = await get_agent(db, tenant_id, agent_id)

    # exclude_unset distinguishes "field omitted" from "field set to null", so
    # a PATCH touching one field cannot blank out the rest.
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("An agent with this name already exists.") from exc
    return agent


async def delete_agent(db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    agent = await get_agent(db, tenant_id, agent_id)
    await db.delete(agent)
    await db.flush()
