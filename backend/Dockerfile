# syntax=docker/dockerfile:1
#
# Build context is the REPO ROOT (see docker-compose.yml's
# `build: {context: ., dockerfile: backend/Dockerfile}`), not this directory
# — needed so this stage can reach widget/ to build it, the same reasoning
# nginx/Dockerfile already has. This image bakes in and serves the widget
# bundle itself (see app/api/widget_static.py) so a deployment with no
# reverse proxy in front of it (e.g. Render, where this backend is the
# public origin) still has somewhere for /widget.js to come from — behind
# nginx (docker-compose.yml), nginx's own `location = /widget.js` still
# intercepts the request first, so this is additive, not a replacement.

FROM node:20-slim AS widget-build
WORKDIR /widget
COPY widget/package.json widget/package-lock.json ./
RUN npm ci
COPY widget/. .
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

# Separate layer from the app code so `docker build` only reinstalls deps
# when requirements.txt actually changes. sentence-transformers pulls in a
# CPU-only torch wheel — the slow, large part of this install (see README).
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .
COPY --from=widget-build /widget/dist/widget.js ./static/widget.js

EXPOSE 8000

# Runs migrations, then starts the API with multiple worker processes —
# exactly the scenario Step 10's Redis-backed rate limiter exists for (the
# in-memory backend only coordinates correctly within a single process).
# docker-compose.yml's depends_on/condition:service_healthy ensures Postgres
# is actually ready before this container starts, so `alembic upgrade head`
# here isn't racing a database that doesn't exist yet.
#
# ${PORT:-8000}: unset in docker-compose.yml (falls back to 8000, matching
# nginx.conf's proxy_pass and every EXPOSE/healthcheck in this repo), but a
# platform that assigns its own port to bind (Render) sets PORT itself —
# hardcoding 8000 there would make the container unreachable.
#
# This assumes exactly one backend *container* (internally multi-process via
# --workers) — running several container replicas would need migrations
# moved to a separate one-shot init step to avoid concurrent migration
# races. Out of scope here; noted for when that's actually needed.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 4"]
