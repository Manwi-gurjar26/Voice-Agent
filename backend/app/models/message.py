from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class Message(Base, UUIDMixin, TimestampMixin):
    """One turn in a conversation. `input_tokens`/`output_tokens` are only
    populated on assistant rows — they come from Claude's usage block, which
    a user-authored message obviously has none of."""

    __tablename__ = "messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{"document_id": "...", "title": "..."}, ...] — only populated on an
    # assistant row when retrieval (Step 5) found relevant chunks for that
    # turn. Denormalized title: a citation is a point-in-time record of what
    # was used to answer, like a citation in a paper — if the source
    # document is later renamed, this should still show what it was called
    # at the time, not require a join to (possibly missing) current state.
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")

    def __repr__(self) -> str:
        return f"<Message {self.role} conv={self.conversation_id}>"
