from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class PasswordResetToken(Base, UUIDMixin, TimestampMixin):
    """One issued password-reset token.

    Same shape as RefreshToken (app/models/refresh_token.py) and for the same
    reason: an opaque random string, not a JWT, so only its HMAC needs to be
    stored — a database leak alone doesn't yield a usable token. `used_at`,
    not `revoked_at`: this is single-use by design (reset it, and it's spent),
    not something that gets revoked out from under a still-valid use.
    """

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(lazy="raise")

    def is_usable(self, now: datetime) -> bool:
        return self.used_at is None and self.expires_at > now

    def __repr__(self) -> str:
        return f"<PasswordResetToken user={self.user_id} used={self.used_at is not None}>"
