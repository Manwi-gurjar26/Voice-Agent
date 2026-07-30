from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.models.enums import PlanTier

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User


class Tenant(Base, UUIDMixin, TimestampMixin):
    """A customer account. Every other tenant-owned row hangs off this."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "plan IN ('free', 'starter', 'pro', 'enterprise')",
            name="plan_valid",
        ),
        CheckConstraint("monthly_message_quota >= 0", name="quota_non_negative"),
        CheckConstraint("messages_used_in_period >= 0", name="messages_used_non_negative"),
        # Postgres allows multiple NULLs in a unique column, so this only
        # constrains tenants that have actually checked out at least once.
        UniqueConstraint("stripe_customer_id", name="uq_tenants_stripe_customer_id"),
        UniqueConstraint("stripe_subscription_id", name="uq_tenants_stripe_subscription_id"),
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    plan: Mapped[PlanTier] = mapped_column(
        String(20), nullable=False, default=PlanTier.FREE, server_default="free"
    )
    monthly_message_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1_000, server_default="1000"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # --- Usage quota (Step 4) ---
    # A rolling 30-day window, not a calendar month — reset logic lives in
    # app/services/quota.py. Calendar-aligned billing periods are a Step 9
    # billing concern, not a Step 4 metering one.
    messages_used_in_period: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    period_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # --- Billing (Step 9) ---
    # Both null for a tenant that has never checked out. stripe_customer_id
    # outlives a cancelled subscription (see downgrade_to_free) so a
    # returning customer reuses the same Stripe Customer instead of a new
    # one being created on every resubscribe.
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    users: Mapped[list[User]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="raise"
    )
    agents: Mapped[list[Agent]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", lazy="raise"
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.slug!r}>"
