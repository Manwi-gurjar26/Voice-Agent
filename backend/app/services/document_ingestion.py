"""Extracts text from a paste/file/URL, chunks it, embeds each chunk, and
persists the result.

Ingestion runs synchronously within the request that creates the Document —
see README's RAG section for the tradeoff and the size/time caps
(`settings.max_pasted_text_chars`, `max_upload_file_bytes`,
`url_fetch_timeout_seconds`, `max_url_response_bytes`) that bound worst-case
request latency. A later move to background processing needs no schema
change: `Document.status` already exists for exactly that reason.
"""

from __future__ import annotations

import io

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.models import Chunk, Document
from app.services import embeddings
from app.services.chunking import chunk_text


class IngestionError(AppError):
    """A problem extracting or processing content. Callers persist this as
    Document.status='failed' + error_message — the Document row itself was
    still created successfully, so this is never raised as an HTTP error."""

    code = "ingestion_failed"
    message = "Could not process this document."


def extract_text_from_upload(filename: str, content: bytes) -> str:
    """CPU-bound and potentially slow for a large PDF — callers should run
    this via `asyncio.to_thread` rather than calling it directly from an
    async request handler."""
    lower = filename.lower()
    if lower.endswith(".pdf"):
        try:
            reader = PdfReader(io.BytesIO(content))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise IngestionError(f"Could not read this PDF: {exc}") from exc
    if lower.endswith((".txt", ".md")):
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IngestionError("File is not valid UTF-8 text.") from exc
    raise IngestionError("Unsupported file type. Upload a .txt, .md, or .pdf file.")


def _build_http_client() -> httpx.AsyncClient:
    """The one mockable seam for URL fetching — same pattern as
    get_anthropic_client / get_embedding_model. Tests monkeypatch this to
    return a client wired to httpx.MockTransport instead of hitting the
    network."""
    return httpx.AsyncClient(follow_redirects=True, timeout=settings.url_fetch_timeout_seconds)


async def fetch_url_text(url: str) -> tuple[str, str | None]:
    """Fetch a single page and extract its visible text. Not a crawler — one
    URL in, one Document out; the caller adds more URLs one at a time.

    Returns (text, page_title_or_None). Caps the read at
    `max_url_response_bytes` regardless of what Content-Length claims (a
    server can lie about or omit it), by checking the running total as
    bytes actually arrive rather than trusting the header up front.
    """
    try:
        async with _build_http_client() as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type:
                    raise IngestionError(
                        f"URL did not return HTML or text content "
                        f"(got {content_type or 'unknown content type'})."
                    )
                buffer = bytearray()
                async for piece in response.aiter_bytes():
                    buffer.extend(piece)
                    if len(buffer) > settings.max_url_response_bytes:
                        raise IngestionError("Page content is too large.")
                body = bytes(buffer)
    except httpx.HTTPStatusError as exc:
        raise IngestionError(f"URL returned HTTP {exc.response.status_code}.") from exc
    except httpx.HTTPError as exc:
        raise IngestionError(f"Could not fetch URL: {exc}") from exc

    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None
    return soup.get_text(separator="\n"), title


async def ingest_document(db: AsyncSession, document: Document, raw_text: str) -> None:
    """Chunk, embed, and stage Chunk rows plus the document's ready state.

    Does not commit — the caller (an endpoint) commits once, after either
    this succeeds or the caller has recorded a failure, so a document never
    sits in the ambiguous state of "some chunks written, status still
    processing". Raises IngestionError on empty extracted content; the
    caller is responsible for catching it and recording failure.
    """
    pieces = chunk_text(
        raw_text, chunk_size=settings.chunk_size_chars, overlap=settings.chunk_overlap_chars
    )
    if not pieces:
        raise IngestionError("No text content could be extracted from this document.")

    vectors = await embeddings.embed_texts(pieces)

    for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
        db.add(
            Chunk(
                document_id=document.id,
                tenant_id=document.tenant_id,
                agent_id=document.agent_id,
                chunk_index=index,
                content=piece,
                embedding=vector,
            )
        )

    document.status = "ready"
    document.char_count = len(raw_text)
    document.error_message = None
