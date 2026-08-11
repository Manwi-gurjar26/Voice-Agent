"""Website crawling for the knowledge base — one Document per discovered
page, not one Document for the whole site (see app/models/document.py's
docstring for why).

Firecrawl's crawl job is asynchronous on their side: POST /v1/crawl starts
it and returns a job id immediately; the actual scraping happens on
Firecrawl's servers, discovered here by polling GET /v1/crawl/{id} until
status == "completed" — confirmed directly against the real API before
writing this, since the response shape (`data: [{"markdown": ..., "metadata":
{"title": ..., "url": ...}}]`) isn't obvious from the endpoint name alone.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.core.config import settings
from app.core.errors import AppError

_BASE_URL = "https://api.firecrawl.dev/v1"


class CrawlError(AppError):
    """Raised when a crawl can't be started, fails on Firecrawl's side, or
    doesn't finish within crawl_poll_timeout_seconds. Unlike a single-URL
    fetch failure, no Document row exists yet at this point — there is
    nothing to crawl into per-page Documents — so this is surfaced as a
    normal HTTP error, the same as `upload_document`'s pre-Document
    file-too-large rejection."""

    code = "crawl_failed"
    message = "Could not crawl this website."
    status_code = 502


class CrawledPage:
    __slots__ = ("url", "title", "markdown")

    def __init__(self, url: str, title: str | None, markdown: str) -> None:
        self.url = url
        self.title = title
        self.markdown = markdown


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.firecrawl_api_key}",
        "Content-Type": "application/json",
    }


def _build_http_client() -> httpx.AsyncClient:
    """The one mockable seam for Firecrawl calls — same pattern as
    document_ingestion._build_http_client. Tests monkeypatch this to return
    a client wired to httpx.MockTransport instead of hitting the network."""
    return httpx.AsyncClient(timeout=30.0)


async def scrape_page(url: str) -> CrawledPage | None:
    """Scrape exactly one page. Returns None if it yields no text."""
    async with _build_http_client() as client:
        try:
            response = await client.post(
                f"{_BASE_URL}/scrape",
                headers=_headers(),
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "waitFor": settings.crawl_wait_for_ms,
                },
            )
            response.raise_for_status()
            data = response.json().get("data") or {}
        except Exception as exc:
            raise CrawlError(f"Could not fetch {url}: {exc}") from exc

    markdown = data.get("markdown") or ""
    if not markdown.strip():
        return None
    metadata = data.get("metadata") or {}
    return CrawledPage(
        url=metadata.get("url") or metadata.get("sourceURL") or url,
        title=metadata.get("title"),
        markdown=markdown,
    )


async def crawl_site(url: str, limit: int) -> list[CrawledPage]:
    """Starts a Firecrawl job for `url` (capped at `limit` pages) and polls
    until it completes, returning one CrawledPage per discovered page.

    `scrapeOptions.waitFor` gives each page's client-side JS time to render
    before Firecrawl captures it — without it, a JS-rendered site (Streamlit,
    a React/Vue SPA, etc.) yields only its loading shell, not real content.
    `excludePaths` skips non-content system files a crawler would otherwise
    discover and scrape as if they were pages.

    A crawl started from a deep link ("…/features/") commonly finds nothing at
    all: Firecrawl only follows links *below* the start path, and does not
    include the start page itself — confirmed live, where that URL crawled to
    0 pages while scraping the very same URL returned 12k characters. Rather
    than hand back an empty knowledge base that still looks like a successful
    import, the start page is fetched directly in that case.
    """
    pages = await _run_crawl_job(url, limit)
    if pages:
        return pages

    single = await scrape_page(url)
    if single is not None:
        return [single]
    raise CrawlError(
        f"Found no readable pages at {url}. Check the address, or try the "
        f"site's home page instead of a link to one section."
    )


async def _run_crawl_job(url: str, limit: int) -> list[CrawledPage]:
    async with _build_http_client() as client:
        try:
            start = await client.post(
                f"{_BASE_URL}/crawl",
                headers=_headers(),
                json={
                    "url": url,
                    "limit": limit,
                    "scrapeOptions": {
                        "formats": ["markdown"],
                        "waitFor": settings.crawl_wait_for_ms,
                    },
                    "excludePaths": ["/sitemap.xml", "/robots.txt"],
                },
            )
            start.raise_for_status()
            job_id = start.json()["id"]
        except Exception as exc:
            raise CrawlError(f"Could not start crawling {url}: {exc}") from exc

        deadline = time.monotonic() + settings.crawl_poll_timeout_seconds
        while True:
            try:
                status_response = await client.get(f"{_BASE_URL}/crawl/{job_id}", headers=_headers())
                status_response.raise_for_status()
                body = status_response.json()
            except Exception as exc:
                # A single flaky poll (confirmed live: Firecrawl's status
                # endpoint occasionally 502s transiently) shouldn't fail the
                # whole crawl — the job keeps running server-side regardless.
                # Only the timeout below gives up for real.
                if time.monotonic() > deadline:
                    raise CrawlError(f"Could not check crawl status for {url}: {exc}") from exc
                await asyncio.sleep(settings.crawl_poll_interval_seconds)
                continue

            status = body.get("status")
            if status == "completed":
                return [
                    CrawledPage(
                        url=(item.get("metadata") or {}).get("url") or url,
                        title=(item.get("metadata") or {}).get("title"),
                        markdown=item.get("markdown") or "",
                    )
                    for item in body.get("data", [])
                    # Belt-and-suspenders: excludePaths above doesn't
                    # reliably keep Firecrawl from auto-discovering and
                    # scraping a site's own sitemap.xml/robots.txt as if it
                    # were a content page (confirmed live) — those are never
                    # useful chunks for a knowledge base.
                    if not _is_non_content_path((item.get("metadata") or {}).get("url") or "")
                ]
            if status in ("failed", "cancelled"):
                raise CrawlError(f"Firecrawl could not crawl {url} (status: {status}).")
            if time.monotonic() > deadline:
                raise CrawlError(f"Timed out waiting for {url} to finish crawling.")
            await asyncio.sleep(settings.crawl_poll_interval_seconds)


_NON_CONTENT_SUFFIXES = ("/sitemap.xml", "/robots.txt")


def _is_non_content_path(page_url: str) -> bool:
    path = httpx.URL(page_url).path if page_url else ""
    return path.endswith(_NON_CONTENT_SUFFIXES)
