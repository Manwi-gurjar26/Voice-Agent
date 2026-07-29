"""Cross-cutting HTTP middleware."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import settings
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID, exposes it on the response, and logs one line
    per request with its duration."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        # Don't trust a client-supplied value verbatim — cap it and strip
        # anything that could forge structure in a log line.
        request_id = (
            "".join(c for c in incoming if c.isalnum() or c in "-_")[:64] or uuid.uuid4().hex
        )
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "%s %s failed after %.1fms", request.method, request.url.path, elapsed_ms
            )
            raise
        finally:
            request_id_ctx.reset(token)

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s -> %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra={
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security headers. The widget's own CSP is set in Step 6."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


_PUBLIC_PREFIX = f"{settings.api_v1_prefix}/public"
_PUBLIC_AGENT_PATH_RE = re.compile(re.escape(f"{_PUBLIC_PREFIX}/agents/") + r"([^/]+)")


class CorsMiddleware(BaseHTTPMiddleware):
    """The only CORS layer in this app — two policies, chosen by path.

    - `/public/*` (the widget API): a per-agent, database-backed allowlist.
      Preflight for these routes is answered by explicit dependency-injected
      route handlers in app/api/v1/public.py (see their docstrings), which
      run the exact same `resolve_public_agent` check as the real request.
      This middleware's only job for these paths is copying the origin —
      already validated and stashed on `request.state.cors_origin` — onto the
      response.
    - Everything else (the dashboard API): one static allowlist from
      `settings.dashboard_cors_origins`, handled entirely here, since a fixed
      list needs no per-request database lookup.

    These two policies live in one middleware, not Starlette's CORSMiddleware
    plus a second custom one for /public/*, because CORSMiddleware intercepts
    *any* OPTIONS request carrying `Access-Control-Request-Method` —
    including ones aimed at /public/* — and answers it from its own static
    list before the request ever reaches the router or this middleware's own
    logic. Wrapping a second CORS-aware middleware around it does not fix
    that: `call_next()` always invokes the full remaining chain, so there is
    no way for an outer middleware to make an inner one skip a request.
    (This is exactly what happened during development: with
    dashboard_cors_origins configured — the normal .env / production case —
    every widget preflight was answered "Disallowed CORS origin" by
    Starlette's middleware, and the widget could never actually reach this
    app's public routes. The test suite didn't catch it because tests run
    with dashboard_cors_origins empty, which skips adding that middleware
    entirely — see test_public.py's dashboard-CORS regression test.)
    """

    def __init__(self, app, dashboard_origins: list[str]) -> None:
        super().__init__(app)
        self._dashboard_origins = set(dashboard_origins)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path.startswith(_PUBLIC_PREFIX):
            return await self._dispatch_public(request, call_next)
        return await self._dispatch_dashboard(request, call_next)

    async def _dispatch_public(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        origin = request.headers.get("Origin")
        response = await call_next(request)

        validated_origin = getattr(request.state, "cors_origin", None)
        if validated_origin:
            response.headers["Access-Control-Allow-Origin"] = validated_origin
            response.headers["Vary"] = "Origin"
        elif origin and not _PUBLIC_AGENT_PATH_RE.match(path):
            # Routes with no {public_key} in the path (e.g. /public/sessions/me)
            # can't be origin-checked before the real request runs — a CORS
            # preflight carries no Authorization value. Enforcement there is
            # the bearer token plus the origin re-check inside the dependency,
            # not this header; reflecting the origin only governs whether the
            # browser lets the page read whatever that dependency returned.
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        return response

    async def _dispatch_dashboard(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        origin = request.headers.get("Origin")
        if not self._dashboard_origins or not origin:
            return await call_next(request)

        allowed = origin in self._dashboard_origins
        is_preflight = (
            request.method == "OPTIONS" and "access-control-request-method" in request.headers
        )
        if is_preflight:
            if not allowed:
                return Response(status_code=400, content="Disallowed CORS origin")
            return Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type",
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )

        response = await call_next(request)
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
            response.headers["Vary"] = "Origin"
        return response
