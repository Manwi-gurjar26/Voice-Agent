from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Chunk, Document
from app.services import document_ingestion, firecrawl
from tests.test_auth import PASSWORD, bearer, register
from tests.test_public import make_active_agent


def _make_minimal_pdf(text: str) -> bytes:
    """A hand-crafted, genuinely valid single-page PDF containing `text` as
    extractable content — not a mock of pypdf, the real library reads this.
    Verified directly against pypdf before use here (see conversation)."""
    content_stream = f"BT /F1 24 Tf 100 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content_stream)).encode() + b" >>\nstream\n"
        + content_stream
        + b"\nendstream",
    ]
    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_offset = len(buf)
    buf += f"xref\n0 {len(objects) + 1}\n".encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += (
        b"trailer\n"
        + f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode()
        + b"startxref\n"
        + f"{xref_offset}\n".encode()
        + b"%%EOF"
    )
    return bytes(buf)


@pytest.fixture(autouse=True)
def _fake_embeddings(monkeypatch):
    """Deterministic, fast stand-in for the real ~90MB model — this file
    tests ingestion plumbing (CRUD, extraction, chunking-into-rows), not
    retrieval ranking (that's test_retrieval.py) or embedding quality
    (test_embeddings.py, which uses the real model)."""

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[float(i), float(len(t))] for i, t in enumerate(texts)]

    from app.services import embeddings

    monkeypatch.setattr(embeddings, "embed_texts", fake_embed_texts)


PREFIX = settings.api_v1_prefix


async def make_agent_id(client, tokens) -> str:
    agent = await make_active_agent(client, tokens)
    return agent["id"]


# --------------------------------------------------------------------------
# Pasted-text documents
# --------------------------------------------------------------------------
async def test_create_text_document_ingests_synchronously_and_returns_ready(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "text", "title": "FAQ", "content": "We are open 9 to 5, Monday to Friday."},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["source_type"] == "text"
    assert body["char_count"] == len("We are open 9 to 5, Monday to Friday.")


async def test_text_document_produces_chunk_rows(client, db_session):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    created = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "text", "title": "Policy", "content": "Refunds are available within 30 days."},
        headers=bearer(tokens),
    )
    document_id = created.json()["id"]

    rows = list(
        await db_session.scalars(select(Chunk).where(Chunk.document_id == document_id))
    )
    assert len(rows) == 1
    assert rows[0].content == "Refunds are available within 30 days."
    assert rows[0].embedding == [0.0, float(len("Refunds are available within 30 days."))]


async def test_pasted_content_over_the_size_cap_is_rejected(client, monkeypatch):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    monkeypatch.setattr(settings, "max_pasted_text_chars", 10)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "text", "title": "Too long", "content": "x" * 11},
        headers=bearer(tokens),
    )
    assert response.status_code == 422


async def test_deleting_a_document_cascades_to_its_chunks(client, db_session):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    created = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "text", "title": "Temp", "content": "Some content here."},
        headers=bearer(tokens),
    )
    document_id = created.json()["id"]

    response = await client.delete(
        f"{PREFIX}/agents/{agent_id}/documents/{document_id}", headers=bearer(tokens)
    )
    assert response.status_code == 204

    assert (await db_session.scalar(select(Document).where(Document.id == document_id))) is None
    assert (
        await db_session.scalar(select(Chunk).where(Chunk.document_id == document_id))
    ) is None


# --------------------------------------------------------------------------
# List / get
# --------------------------------------------------------------------------
async def test_list_documents_returns_only_this_agents_documents(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    other_agent = await make_active_agent(client, tokens, name="Other Bot")
    other_agent_id = other_agent["id"]

    await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "text", "title": "Doc A", "content": "Content A"},
        headers=bearer(tokens),
    )

    listing = await client.get(f"{PREFIX}/agents/{other_agent_id}/documents", headers=bearer(tokens))
    assert listing.status_code == 200
    assert listing.json()["items"] == []


async def test_get_unknown_document_is_404(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    response = await client.get(
        f"{PREFIX}/agents/{agent_id}/documents/00000000-0000-0000-0000-000000000000",
        headers=bearer(tokens),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Tenant / agent isolation
# --------------------------------------------------------------------------
async def test_cannot_list_documents_for_another_tenants_agent(client):
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent_a_id = await make_agent_id(client, tokens_a)

    response = await client.get(f"{PREFIX}/agents/{agent_a_id}/documents", headers=bearer(tokens_b))
    assert response.status_code == 404  # agent lookup itself fails cross-tenant


async def test_cannot_read_another_tenants_document_even_with_own_agent_id(client):
    """Belt and suspenders: get_document filters by BOTH tenant_id and
    agent_id, not just document_id — this proves the tenant filter, not just
    the agent-ownership dependency, is what's doing the work."""
    tokens_a = await register(client, email="a@acme.example.com", company="Acme")
    tokens_b = await register(client, email="b@globex.example.com", company="Globex")
    agent_a_id = await make_agent_id(client, tokens_a)
    created = await client.post(
        f"{PREFIX}/agents/{agent_a_id}/documents",
        json={"source_type": "text", "title": "Secret", "content": "Confidential info."},
        headers=bearer(tokens_a),
    )
    document_id = created.json()["id"]

    # tokens_b has no agent with this id at all, so this 404s at the agent
    # dependency layer — the intended, earliest possible rejection point.
    response = await client.get(
        f"{PREFIX}/agents/{agent_a_id}/documents/{document_id}", headers=bearer(tokens_b)
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# RBAC
# --------------------------------------------------------------------------
async def test_member_can_list_but_not_create_documents(client, db_session):
    from app.core.security import hash_password
    from app.models import User
    from app.models.enums import UserRole

    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    owner = await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    db_session.add(
        User(
            tenant_id=owner.tenant_id,
            email="member@acme.example.com",
            hashed_password=hash_password(PASSWORD),
            role=UserRole.MEMBER,
        )
    )
    await db_session.flush()
    member_login = await client.post(
        f"{PREFIX}/auth/login", json={"email": "member@acme.example.com", "password": PASSWORD}
    )
    member_tokens = member_login.json()

    listing = await client.get(f"{PREFIX}/agents/{agent_id}/documents", headers=bearer(member_tokens))
    assert listing.status_code == 200

    created = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "text", "title": "X", "content": "Y"},
        headers=bearer(member_tokens),
    )
    assert created.status_code == 403


async def test_documents_endpoints_require_auth(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    response = await client.get(f"{PREFIX}/agents/{agent_id}/documents")
    assert response.status_code == 401


# --------------------------------------------------------------------------
# File upload
# --------------------------------------------------------------------------
async def test_upload_a_txt_file(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("notes.txt", b"Our support hours are 9-5.", "text/plain")},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["original_filename"] == "notes.txt"


async def test_upload_a_markdown_file(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("readme.md", b"# Title\n\nSome **markdown** content.", "text/markdown")},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "ready"


async def test_upload_a_real_pdf_file(client, db_session):
    """Uses a genuinely valid, hand-crafted PDF — not a mock of pypdf —
    verified directly against pypdf before being used as a fixture here."""
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    pdf_bytes = _make_minimal_pdf("Hello PDF World")

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("manual.pdf", pdf_bytes, "application/pdf")},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"

    rows = list(
        await db_session.scalars(select(Chunk).where(Chunk.document_id == body["id"]))
    )
    assert len(rows) == 1
    assert "Hello PDF World" in rows[0].content


async def test_upload_rejects_unsupported_file_type(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("image.png", b"\x89PNG\r\n", "image/png")},
        headers=bearer(tokens),
    )
    assert response.status_code == 201  # the Document row is still created...
    assert response.json()["status"] == "failed"  # ...just marked failed, not an HTTP error
    assert "unsupported" in response.json()["error_message"].lower()


async def test_upload_rejects_non_utf8_text_file(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("bad.txt", b"\xff\xfe not valid utf-8", "text/plain")},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"


async def test_upload_rejects_a_corrupt_pdf(client):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("broken.pdf", b"%PDF-1.4 this is not a real pdf structure", "application/pdf")},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"


async def test_upload_over_the_size_cap_is_rejected_outright(client, monkeypatch):
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    monkeypatch.setattr(settings, "max_upload_file_bytes", 10)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/upload",
        files={"file": ("big.txt", b"x" * 11, "text/plain")},
        headers=bearer(tokens),
    )
    # 413, not a created-then-failed document: this is "never attempted",
    # distinct from an extraction failure.
    assert response.status_code == 413


# --------------------------------------------------------------------------
# URL ingestion (httpx.MockTransport — no real network access)
# --------------------------------------------------------------------------
def _install_mock_transport(monkeypatch, handler):
    def fake_build_client():
        return httpx.AsyncClient(
            follow_redirects=True, transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr(document_ingestion, "_build_http_client", fake_build_client)


async def test_add_document_from_a_url(client, monkeypatch, db_session):
    html = b"<html><head><title>Support Page</title></head><body><p>Call us anytime.</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html)

    _install_mock_transport(monkeypatch, handler)

    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "url", "url": "https://example.com/support"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["title"] == "Support Page"  # derived from <title> since none was supplied

    rows = list(await db_session.scalars(select(Chunk).where(Chunk.document_id == body["id"])))
    assert any("Call us anytime" in r.content for r in rows)


async def test_explicit_title_overrides_the_pages_title_tag(client, monkeypatch):
    html = b"<html><head><title>Ignored</title></head><body>Text.</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=html)

    _install_mock_transport(monkeypatch, handler)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "url", "title": "My Chosen Title", "url": "https://example.com"},
        headers=bearer(tokens),
    )
    assert response.json()["title"] == "My Chosen Title"


async def test_url_returning_non_html_content_is_marked_failed(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    _install_mock_transport(monkeypatch, handler)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "url", "url": "https://example.com/api"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"


async def test_url_returning_an_error_status_is_marked_failed(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, headers={"content-type": "text/html"}, content=b"not found")

    _install_mock_transport(monkeypatch, handler)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "url", "url": "https://example.com/missing"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert "404" in body["error_message"]


async def test_oversized_url_response_is_marked_failed(client, monkeypatch):
    monkeypatch.setattr(settings, "max_url_response_bytes", 10)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>" + b"x" * 100 + b"</html>"
        )

    _install_mock_transport(monkeypatch, handler)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "url", "url": "https://example.com/huge"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"


async def test_unreachable_url_is_marked_failed_not_a_500(client, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    _install_mock_transport(monkeypatch, handler)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents",
        json={"source_type": "url", "url": "https://unreachable.example.com"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"


# --------------------------------------------------------------------------
# Website-crawl ingestion (Firecrawl, httpx.MockTransport — no real network)
# --------------------------------------------------------------------------
def _install_fake_firecrawl(monkeypatch, poll_responses: list[dict], start_status: int = 200):
    """`poll_responses` is consumed one response per GET /v1/crawl/{id} call
    — the last entry repeats if polled more times than the list's length,
    so a single-entry list (the common "completed on the first poll" case)
    doesn't need padding."""
    calls = {"polls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if start_status != 200:
                return httpx.Response(start_status, json={"error": "nope"})
            return httpx.Response(200, json={"success": True, "id": "job123"})
        index = min(calls["polls"], len(poll_responses) - 1)
        calls["polls"] += 1
        return httpx.Response(200, json=poll_responses[index])

    def fake_build_client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(firecrawl, "_build_http_client", fake_build_client)
    monkeypatch.setattr(settings, "crawl_poll_interval_seconds", 0.0)
    return calls


async def test_crawl_creates_one_document_per_page(client, monkeypatch, db_session):
    _install_fake_firecrawl(
        monkeypatch,
        [
            {
                "status": "completed",
                "data": [
                    {
                        "markdown": "Home page content here.",
                        "metadata": {"title": "Home", "url": "https://example.com/"},
                    },
                    {
                        "markdown": "About us content here.",
                        "metadata": {"title": "About", "url": "https://example.com/about"},
                    },
                ],
            }
        ],
    )
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com", "limit": 10},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["items"]) == 2
    assert {d["title"] for d in body["items"]} == {"Home", "About"}
    assert all(d["source_type"] == "crawl" for d in body["items"])
    assert all(d["status"] == "ready" for d in body["items"])

    rows = list(await db_session.scalars(select(Document).where(Document.source_type == "crawl")))
    assert len(rows) == 2


async def test_crawl_polls_until_completed(client, monkeypatch):
    calls = _install_fake_firecrawl(
        monkeypatch,
        [
            {"status": "scraping", "data": []},
            {"status": "scraping", "data": []},
            {
                "status": "completed",
                "data": [
                    {"markdown": "Content.", "metadata": {"title": "Page", "url": "https://example.com/"}}
                ],
            },
        ],
    )
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["items"]) == 1
    assert calls["polls"] == 3  # two "still scraping" polls, then completed


async def test_crawl_request_caps_limit_at_max_crawl_pages(client, monkeypatch):
    monkeypatch.setattr(settings, "max_crawl_pages", 5)
    requested_limits: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            import json as _json

            requested_limits.append(_json.loads(request.content)["limit"])
            return httpx.Response(200, json={"success": True, "id": "job123"})
        # One page, not zero: an empty crawl now falls back to scraping the
        # start URL, which isn't what this test is about.
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "data": [
                    {"markdown": "Content.", "metadata": {"title": "P", "url": "https://example.com/"}}
                ],
            },
        )

    monkeypatch.setattr(
        firecrawl, "_build_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(settings, "crawl_poll_interval_seconds", 0.0)

    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com", "limit": 100},  # over max_crawl_pages
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    assert requested_limits == [5]  # capped server-side, not the requested 100


async def test_crawl_start_failure_is_a_clean_error(client, monkeypatch):
    _install_fake_firecrawl(monkeypatch, [{"status": "completed", "data": []}], start_status=500)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com"},
        headers=bearer(tokens),
    )
    # No Document exists yet at this point — a clean error, not a 500.
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "crawl_failed"


async def test_crawl_timeout_is_a_clean_error(client, monkeypatch):
    _install_fake_firecrawl(monkeypatch, [{"status": "scraping", "data": []}])
    monkeypatch.setattr(settings, "crawl_poll_timeout_seconds", 0.0)
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com"},
        headers=bearer(tokens),
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "crawl_failed"


async def test_crawl_page_with_no_extractable_text_is_marked_failed_others_still_succeed(
    client, monkeypatch
):
    _install_fake_firecrawl(
        monkeypatch,
        [
            {
                "status": "completed",
                "data": [
                    {"markdown": "", "metadata": {"title": "Empty", "url": "https://example.com/empty"}},
                    {
                        "markdown": "Real content.",
                        "metadata": {"title": "Real", "url": "https://example.com/real"},
                    },
                ],
            }
        ],
    )
    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com"},
        headers=bearer(tokens),
    )
    assert response.status_code == 201, response.text
    by_title = {d["title"]: d["status"] for d in response.json()["items"]}
    assert by_title == {"Empty": "failed", "Real": "ready"}


async def test_member_cannot_start_a_crawl(client, db_session):
    from app.core.security import hash_password
    from app.models import User
    from app.models.enums import UserRole

    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    owner = await db_session.scalar(select(User).where(User.email == "owner@acme.example.com"))
    db_session.add(
        User(
            tenant_id=owner.tenant_id,
            email="member2@acme.example.com",
            hashed_password=hash_password(PASSWORD),
            role=UserRole.MEMBER,
        )
    )
    await db_session.flush()
    member_login = await client.post(
        f"{PREFIX}/auth/login", json={"email": "member2@acme.example.com", "password": PASSWORD}
    )
    member_tokens = member_login.json()

    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com"},
        headers=bearer(member_tokens),
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Empty-crawl fallback
#
# Firecrawl only follows links *below* the start path and does not include the
# start page itself, so crawling a deep link ("…/features/") completes with
# zero pages — confirmed live, where that URL crawled to 0 pages while
# scraping the same URL returned ~12k characters. Silently creating an empty
# knowledge base there looks like a successful import but leaves the agent
# knowing nothing about the site.
# --------------------------------------------------------------------------
def _install_crawl_then_scrape(monkeypatch, *, scrape_markdown: str | None):
    """Crawl completes with no pages; scrape returns `scrape_markdown`."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path.endswith("/scrape"):
            data = {"metadata": {"title": "Features", "url": "https://example.com/features/"}}
            if scrape_markdown is not None:
                data["markdown"] = scrape_markdown
            return httpx.Response(200, json={"success": True, "data": data})
        if request.method == "POST":
            return httpx.Response(200, json={"success": True, "id": "job123"})
        return httpx.Response(200, json={"status": "completed", "data": []})

    monkeypatch.setattr(
        firecrawl, "_build_http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(settings, "crawl_poll_interval_seconds", 0.0)
    return seen


async def test_empty_crawl_falls_back_to_scraping_the_start_page(client, monkeypatch):
    seen = _install_crawl_then_scrape(monkeypatch, scrape_markdown="The real page content.")

    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com/features/"},
        headers=bearer(tokens),
    )

    assert response.status_code == 201, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "Features"
    assert items[0]["status"] == "ready"
    assert any("/scrape" in url for url in seen)


async def test_a_crawl_that_finds_nothing_at_all_is_an_error_not_an_empty_import(
    client, monkeypatch
):
    _install_crawl_then_scrape(monkeypatch, scrape_markdown=None)

    tokens = await register(client)
    agent_id = await make_agent_id(client, tokens)
    response = await client.post(
        f"{PREFIX}/agents/{agent_id}/documents/crawl",
        json={"url": "https://example.com/nothing-here"},
        headers=bearer(tokens),
    )

    assert response.status_code == 502
    body = response.json()["error"]
    assert body["code"] == "crawl_failed"
    # The message has to tell the customer what to actually do about it.
    assert "home page" in body["message"]
