from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.document import Document


class Chunk(Base, UUIDMixin, TimestampMixin):
    """One embedded slice of a Document.

    `embedding` is a plain Postgres float array, not a `vector` column —
    pgvector isn't installed on this deployment (see README). Retrieval loads
    an agent's chunks and ranks them with numpy in
    app/services/retrieval.py; that is the one function to replace with a
    native `<=>` ANN query if pgvector is added later. `agent_id` (not just
    `document_id`) is denormalized here specifically because that's what
    every retrieval query filters on — an agent's knowledge base, not a
    single document.
    """

    __tablename__ = "chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # L2-normalized at embedding time (app/services/embeddings.py), so cosine
    # similarity reduces to a plain dot product at retrieval time.
    embedding: Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks", lazy="raise")

    def __repr__(self) -> str:
        return f"<Chunk {self.chunk_index} doc={self.document_id}>"
