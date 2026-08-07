"""Document CRUD, scoped to (tenant, agent) — the knowledge base belongs to
one agent, so every function takes both ids and filters on them."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError
from app.models import Document
from app.services import document_ingestion as ingestion
from app.services import firecrawl
from app.schemas.document import DocumentCreateText, DocumentCreateUrl


async def get_document(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    """Fetch one document within a tenant's agent.

    tenant_id and agent_id are both part of the WHERE clause, so a document
    belonging to another tenant — or another agent of the same tenant — is
    indistinguishable from one that does not exist.
    """
    document = await db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
            Document.agent_id == agent_id,
        )
    )
    if document is None:
        raise NotFoundError("Document not found.")
    return document


async def list_documents(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> tuple[list[Document], int]:
    total = await db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.tenant_id == tenant_id, Document.agent_id == agent_id)
    )
    rows = await db.scalars(
        select(Document)
        .where(Document.tenant_id == tenant_id, Document.agent_id == agent_id)
        .order_by(Document.created_at.desc(), Document.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), int(total or 0)


async def delete_document(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    document = await get_document(db, tenant_id, agent_id, document_id)
    await db.delete(document)
    await db.flush()


async def _finish(db: AsyncSession, document: Document, raw_text: str) -> Document:
    """Shared tail for every creation path: ingest, and on failure record
    why rather than letting the exception escape as an HTTP error — the
    Document row itself was already successfully created."""
    try:
        await ingestion.ingest_document(db, document, raw_text)
    except ingestion.IngestionError as exc:
        document.status = "failed"
        document.error_message = exc.message
    await db.commit()
    return document


async def create_text_document(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, payload: DocumentCreateText
) -> Document:
    document = Document(
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_type="text",
        title=payload.title,
        status="processing",
    )
    db.add(document)
    await db.flush()
    return await _finish(db, document, payload.content)


async def create_url_document(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, payload: DocumentCreateUrl
) -> Document:
    document = Document(
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_type="url",
        title=payload.title or payload.url,
        source_url=payload.url,
        status="processing",
    )
    db.add(document)
    await db.flush()

    try:
        raw_text, page_title = await ingestion.fetch_url_text(payload.url)
    except ingestion.IngestionError as exc:
        document.status = "failed"
        document.error_message = exc.message
        await db.commit()
        return document

    if not payload.title and page_title:
        document.title = page_title[:300]
    return await _finish(db, document, raw_text)


async def create_crawl_documents(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID, url: str, limit: int
) -> list[Document]:
    """Crawl `url` (via Firecrawl) and create one Document per page found.

    A total crawl failure (couldn't start, or timed out — see
    firecrawl.CrawlError) propagates as a normal HTTP error: no Document
    row exists yet at that point, unlike the per-page ingestion below,
    which follows the same create-then-possibly-fail pattern as every other
    document type (a bad page still leaves the other pages' Documents
    ready, exactly like a partially-successful upload wouldn't roll back
    documents that already ingested fine).
    """
    pages = await firecrawl.crawl_site(url, min(limit, settings.max_crawl_pages))

    documents: list[Document] = []
    for page in pages:
        document = Document(
            tenant_id=tenant_id,
            agent_id=agent_id,
            source_type="crawl",
            title=(page.title or page.url)[:300],
            source_url=page.url,
            status="processing",
        )
        db.add(document)
        await db.flush()
        documents.append(await _finish(db, document, page.markdown))
    return documents


async def create_uploaded_document(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    filename: str,
    content: bytes,
) -> Document:
    document = Document(
        tenant_id=tenant_id,
        agent_id=agent_id,
        source_type="file",
        title=filename,
        original_filename=filename,
        status="processing",
    )
    db.add(document)
    await db.flush()

    try:
        # CPU-bound (PDF parsing in particular) — offload so a large upload
        # doesn't block the event loop for every other in-flight request.
        raw_text = await asyncio.to_thread(ingestion.extract_text_from_upload, filename, content)
    except ingestion.IngestionError as exc:
        document.status = "failed"
        document.error_message = exc.message
        await db.commit()
        return document

    return await _finish(db, document, raw_text)
