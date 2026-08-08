"""FastAPI application factory and entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.router import api_router
from app.api.widget_static import router as widget_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import CorsMiddleware, RequestIDMiddleware, SecurityHeadersMiddleware
from app.db.session import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(debug=settings.debug, json_logs=not settings.is_local)
    logger.info("starting %s v%s (env=%s)", settings.app_name, __version__, settings.app_env)
    yield
    await dispose_engine()
    logger.info("shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        # Schema docs are useful in dev and an information leak in production.
        docs_url="/docs" if settings.is_local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.is_local else None,
    )

    # Middleware runs bottom-up: RequestIDMiddleware is added last so it wraps
    # everything (every response, including CORS preflights, gets a request
    # id and a log line). CorsMiddleware is the single owner of every CORS
    # decision in the app — see its docstring for why the dashboard and
    # public-widget policies must not be two separate middleware layers.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorsMiddleware, dashboard_origins=settings.dashboard_cors_origins)
    app.add_middleware(RequestIDMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(widget_router)
    return app


app = create_app()
