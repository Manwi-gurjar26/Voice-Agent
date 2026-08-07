from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.chunk import Chunk


class Document(Base, UUIDMixin, TimestampMixin):
    """One knowledge-base source: pasted text, an uploaded file, a single
    URL, or one page discovered by a Firecrawl site crawl (source_type
    'crawl' — see app/services/firecrawl.py). A crawl produces one Document
    per page it discovers, not one Document for the whole site: this keeps
    citations pointing at the specific page a chunk actually came from,
    consistent with how a single 'url' document already works, rather than
    a new "site" concept with its own chunking/citation semantics.

    `status` tracks ingestion outcome. Ingestion runs synchronously within the
    creating request for this MVP (see README's RAG section for the tradeoff
    and size/time caps that bound it) — `status` still exists as a real
    column, not a placeholder, because a document can genuinely fail to
    ingest (unreachable URL, corrupt PDF) and the dashboard needs to show
    that distinctly from "ready". It also means moving ingestion to a
    background job later is a code change, not a schema change.
    """

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("source_type IN ('text', 'file', 'url', 'crawl')", name="source_type_valid"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')", name="status_valid"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        lazy="raise",
        order_by="Chunk.chunk_index",
    )

    def __repr__(self) -> str:
        return f"<Document {self.title!r} status={self.status}>"
