"""Serves the widget bundle baked into this image (see Dockerfile) at the
same top-level `/widget.js` path nginx has always used — no `/api/v1`
prefix, so this is registered directly on the app, not through api_router.

Only meaningful for a deployment with no reverse proxy in front of this
backend (Render, where this service *is* the public origin). Behind nginx
(docker-compose.yml), nginx's own `location = /widget.js` intercepts the
request first and this route is never reached there — additive, not a
replacement for that.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

router = APIRouter()

# backend/app/api/widget_static.py -> backend/ -> backend/static/widget.js
_WIDGET_PATH = Path(__file__).resolve().parent.parent.parent / "static" / "widget.js"


@router.get("/widget.js", include_in_schema=False)
async def get_widget() -> FileResponse:
    if not _WIDGET_PATH.is_file():
        # Local `docker compose` runs behind nginx, whose own image is the
        # one that bakes in the widget build — this backend image not
        # having one too isn't an error there, just a route nothing ever
        # calls. A platform routing browsers straight to this service
        # (Render) needs the real Dockerfile-baked file, so a 404 here is
        # the honest answer, not a 500 for a missing local build artifact.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "widget.js is not available.")
    return FileResponse(
        _WIDGET_PATH,
        media_type="text/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )
