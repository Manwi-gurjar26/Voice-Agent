from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.api.deps import CurrentUser, DbSession, TenantId, require_roles
from app.core.config import settings
from app.core.errors import AppError
from app.models import Agent
from app.models.enums import UserRole
from app.schemas.document import (
    DocumentCreate,
    DocumentCreateCrawl,
    DocumentCreateText,
    DocumentCreateUrl,
    DocumentListResponse,
    DocumentRead,
)
from app.services import agents as agent_service
from app.services import documents as document_service

router = APIRouter()

# Members may read the knowledge base; changing it is owner/admin only —
# same split as agent configuration itself (Step 2).
WriteAccess = Annotated[CurrentUser, Depends(require_roles(UserRole.OWNER, UserRole.ADMIN))]


async def resolve_owned_agent(agent_id: uuid.UUID, tenant_id: TenantId, db: DbSession) -> Agent:
    """The knowledge base belongs to one agent — verify it exists and
    belongs to this tenant before any document operation touches it."""
    return await agent_service.get_agent(db, tenant_id, agent_id)


OwnedAgent = Annotated[Agent, Depends(resolve_owned_agent)]


@router.get("", response_model=DocumentListResponse, summary="List an agent's knowledge base")
async def list_documents(
    agent: OwnedAgent,
    db: DbSession,
    tenant_id: TenantId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    items, _total = await document_service.list_documents(
        db, tenant_id, agent.id, limit=limit, offset=offset
    )
    return DocumentListResponse(items=[DocumentRead.model_validate(d) for d in items])


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a document from pasted text or a URL",
)
async def create_document(
    payload: DocumentCreate, agent: OwnedAgent, db: DbSession, tenant_id: TenantId, _: WriteAccess
) -> DocumentRead:
    if isinstance(payload, DocumentCreateText):
        document = await document_service.create_text_document(db, tenant_id, agent.id, payload)
    else:
        assert isinstance(payload, DocumentCreateUrl)
        document = await document_service.create_url_document(db, tenant_id, agent.id, payload)
    return DocumentRead.model_validate(document)


@router.post(
    "/crawl",
    response_model=DocumentListResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crawl a website and add one document per page found",
)
async def crawl_documents(
    payload: DocumentCreateCrawl, agent: OwnedAgent, db: DbSession, tenant_id: TenantId, _: WriteAccess
) -> DocumentListResponse:
    documents = await document_service.create_crawl_documents(
        db, tenant_id, agent.id, payload.url, payload.limit
    )
    return DocumentListResponse(items=[DocumentRead.model_validate(d) for d in documents])


@router.post(
    "/upload",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a document from an uploaded .txt, .md, or .pdf file",
)
async def upload_document(
    agent: OwnedAgent,
    db: DbSession,
    tenant_id: TenantId,
    _: WriteAccess,
    file: Annotated[UploadFile, File()],
) -> DocumentRead:
    content = await file.read()
    if len(content) > settings.max_upload_file_bytes:
        # Rejected outright, before any Document row exists — distinct from
        # an extraction failure (bad PDF, wrong extension), which still
        # creates the row and records status='failed' instead. This one is
        # "we never attempted anything", not "we tried and it didn't work".
        limit_mb = settings.max_upload_file_bytes // (1024 * 1024)
        raise AppError(
            f"File exceeds the {limit_mb}MB limit.",
            code="file_too_large",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    document = await document_service.create_uploaded_document(
        db, tenant_id, agent.id, filename=file.filename or "upload", content=content
    )
    return DocumentRead.model_validate(document)


@router.get("/{document_id}", response_model=DocumentRead, summary="Fetch one document")
async def get_document(
    document_id: uuid.UUID, agent: OwnedAgent, db: DbSession, tenant_id: TenantId
) -> DocumentRead:
    document = await document_service.get_document(db, tenant_id, agent.id, document_id)
    return DocumentRead.model_validate(document)


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and its chunks",
)
async def delete_document(
    document_id: uuid.UUID, agent: OwnedAgent, db: DbSession, tenant_id: TenantId, _: WriteAccess
) -> Response:
    await document_service.delete_document(db, tenant_id, agent.id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
