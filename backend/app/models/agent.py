from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.security import generate_agent_public_key
from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import AgentStatus, EffortLevel

if TYPE_CHECKING:
    from app.models.tenant import Tenant


def _default_theme() -> dict[str, Any]:
    return {
        "primaryColor": "#2F6FED",
        "position": "bottom-right",
        "launcherIcon": "chat",
        "bubbleRadius": 16,
    }


class Agent(Base, UUIDMixin, TimestampMixin):
    """One embeddable assistant. `public_key` is what appears in the customer's
    <script> tag; every widget request resolves to exactly one Agent."""

    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("public_key", name="uq_agents_public_key"),
        # Agent names must be unique within a tenant, not globally.
        UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_id_name"),
        CheckConstraint("status IN ('draft', 'active', 'disabled')", name="status_valid"),
        CheckConstraint(
            "effort IN ('low', 'medium', 'high', 'xhigh', 'max')", name="effort_valid"
        ),
        CheckConstraint("rate_limit_per_minute > 0", name="rate_limit_positive"),
        CheckConstraint("max_output_tokens BETWEEN 256 AND 128000", name="max_output_tokens_range"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # No index=True: uq_agents_public_key is already backed by a unique index,
    # so an extra non-unique index on the same column is pure write overhead.
    public_key: Mapped[str] = mapped_column(
        String(80), nullable=False, default=generate_agent_public_key
    )
    status: Mapped[AgentStatus] = mapped_column(
        String(20), nullable=False, default=AgentStatus.DRAFT, server_default="draft"
    )

    # --- Behaviour ---
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="You are a helpful assistant."
    )
    greeting: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="Hi! How can I help you today?"
    )
    model: Mapped[str] = mapped_column(
        String(60), nullable=False, default=lambda: settings.default_model
    )
    # NOTE: current Claude models reject temperature/top_p/top_k with a 400.
    # `effort` is the supported control for reasoning depth and token spend.
    effort: Mapped[EffortLevel] = mapped_column(
        String(10), nullable=False, default=EffortLevel.MEDIUM, server_default="medium"
    )
    max_output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2048, server_default="2048"
    )

    # --- Voice (wired up in Step 7) ---
    voice_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    voice_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # --- Widget presentation & access control ---
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=_default_theme, server_default=text("'{}'::jsonb")
    )
    allowed_origins: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    rate_limit_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )

    tenant: Mapped[Tenant] = relationship(back_populates="agents", lazy="raise")

    # ------------------------------------------------------------------
    @staticmethod
    def normalize_origin(origin: str) -> str:
        """Reduce a URL to a bare `scheme://host[:port]` origin, lowercased.

        Browsers send exactly this in the `Origin` header, so allowlist entries
        must be stored in the same shape or comparisons silently never match.
        """
        parts = urlsplit(origin.strip())
        if not parts.scheme or not parts.netloc:
            raise ValueError(f"origin must include scheme and host: {origin!r}")
        return f"{parts.scheme.lower()}://{parts.netloc.lower()}"

    def is_origin_allowed(self, origin: str | None) -> bool:
        """Exact-match check against the allowlist.

        An empty allowlist denies everything. That is deliberate: defaulting an
        unconfigured agent to open would let anyone embed a tenant's paid agent
        on their own site.
        """
        if not origin or not self.allowed_origins:
            return False
        try:
            candidate = self.normalize_origin(origin)
        except ValueError:
            return False
        return candidate in set(self.allowed_origins)

    def __repr__(self) -> str:
        return f"<Agent {self.name!r} {self.public_key!r}>"
