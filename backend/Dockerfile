# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Separate layer from the app code so `docker build` only reinstalls deps
# when requirements.txt actually changes. sentence-transformers pulls in a
# CPU-only torch wheel — the slow, large part of this install (see README).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

EXPOSE 8000

# Runs migrations, then starts the API with multiple worker processes —
# exactly the scenario Step 10's Redis-backed rate limiter exists for (the
# in-memory backend only coordinates correctly within a single process).
# docker-compose.yml's depends_on/condition:service_healthy ensures Postgres
# is actually ready before this container starts, so `alembic upgrade head`
# here isn't racing a database that doesn't exist yet.
#
# This assumes exactly one backend *container* (internally multi-process via
# --workers) — running several container replicas would need migrations
# moved to a separate one-shot init step to avoid concurrent migration
# races. Out of scope here; noted for when that's actually needed.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4"]
