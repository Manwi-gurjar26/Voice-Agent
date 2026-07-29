from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class WidgetSession(Base, UUIDMixin, TimestampMixin):
    """One browser session of the embedded widget.

    Created when a visitor opens the chat, not on every page load, so this
    table's size tracks engagement rather than pageviews. `tenant_id` is
    denormalized from the agent so Step 4's conversation queries and any
    per-tenant cleanup job can filter without a join back through Agent.
    """

    __tablename__ = "widget_sessions"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Normalized (scheme://host[:port]) at creation time, matching what's
    # stored in Agent.allowed_origins — useful for an "active sessions" admin
    # view without re-deriving it from raw request headers.
    origin: Mapped[str] = mapped_column(String(255), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped[Agent] = relationship(lazy="raise")

    def is_usable(self, now: datetime) -> bool:
        return self.revoked_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return f"<WidgetSession agent={self.agent_id}>"
