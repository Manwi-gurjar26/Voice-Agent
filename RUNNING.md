# How to run this project — step by step

Everything here is written for **this machine** (Windows + PowerShell), and
every command was checked against the actual config files in this repo.

There are **two ways** to run it. Pick one:

| | Way A — Docker | Way B — Local dev |
|---|---|---|
| Command count | 1 | 3 terminals |
| What you get | The whole stack behind nginx, like production | Hot reload on every change |
| Use it when | You want to demo it / test the real thing end to end | You're writing code |
| URL | http://localhost:8080 | http://localhost:3000 |

---

## Way A — Docker (one command, whole stack)

### Prerequisites (already done on this machine)

- Docker Desktop installed and **running** (whale icon in the tray). If it's
  not running, every `docker` command fails with a daemon error.
- `.env` at the repo root — exists ✅
- `backend/.env` — exists ✅

### The command

```powershell
cd "C:\Projects\My project"
docker compose up --build
```

That's it. Then open **http://localhost:8080**

> **First build takes 10–20 minutes.** The backend image installs
> `sentence-transformers` + CPU torch (large, slow). Later builds reuse that
> layer and take seconds unless you change `backend/requirements.txt`.

### What just started (5 containers)

| Container | What it does | Reachable from your browser? |
|---|---|---|
| `nginx` | Front door — routes everything | **Yes → http://localhost:8080** |
| `dashboard` | Next.js dashboard | Only through nginx (`/`) |
| `backend` | FastAPI API + runs migrations on start | Only through nginx (`/api/`) |
| `postgres` | The database | Yes, on **port 5433** (for pgAdmin/DBeaver) |
| `redis` | Rate-limit store | No |

You don't have to run migrations yourself — `backend/Dockerfile` runs
`alembic upgrade head` automatically before starting the API.

### Why port 8080 and not 80?

`docker-compose.override.yml` remaps nginx from `80` → `8080` because **port 80
on this machine is already taken by Windows' own IIS** (confirmed: `netstat`
shows PID 4 / HTTP.sys listening on 80). Same file publishes the container's
Postgres on `5433` because the native PostgreSQL 18 install already owns 5432.

That override file is local-only (it's untracked in git) — a real Linux server
wouldn't need it, and would serve on port 80.

`.env`'s `PUBLIC_ORIGIN` is already set to `http://localhost:8080` to match.
**If you ever change `PUBLIC_ORIGIN`, you must rebuild**, not just restart —
Next.js bakes `NEXT_PUBLIC_API_BASE_URL` into the image at build time:

```powershell
docker compose up --build --force-recreate dashboard
```

### Everyday Docker commands

```powershell
docker compose up --build            # start (rebuild changed images)
docker compose up -d                 # start in background
docker compose ps                    # what's running + health status
docker compose logs -f backend       # follow one service's logs
docker compose logs -f               # follow everything
docker compose restart backend       # restart one service
docker compose down                  # stop everything (KEEPS the database)
docker compose down -v               # stop + DELETE the database volume
docker compose exec backend sh       # shell inside the backend container
docker compose exec backend alembic upgrade head   # run migrations manually
```

Use `down -v` when you want a genuinely clean slate — it wipes all signups,
agents, and documents.

---

## Way B — Local dev (hot reload, 3 terminals)

This runs each piece directly on Windows against the **native** PostgreSQL on
port 5432 — a different database from the Docker one on 5433. Signups you make
in Docker won't exist here, and vice versa.

### Terminal 1 — Backend (FastAPI, port 8000)

```powershell
cd "C:\Projects\My project\backend"
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive API docs: http://127.0.0.1:8000/docs *(local/test only)*

<details>
<summary>First-time-only backend setup (already done here — expand if starting fresh)</summary>

```powershell
cd "C:\Projects\My project\backend"

# 1. Virtual environment (slow: torch + sentence-transformers)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Config
Copy-Item .env.example .env
#    then edit .env — set DATABASE_URL credentials, and generate SECRET_KEY:
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"

# 3. Create the app + test databases
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f scripts/bootstrap_db.sql

# 4. Migrations
.\.venv\Scripts\alembic.exe upgrade head
```
</details>

### Terminal 2 — Dashboard (Next.js, port 3000)

```powershell
cd "C:\Projects\My project\dashboard"
npm run dev
```

Open **http://localhost:3000**

`dashboard/.env.local` already points at `http://127.0.0.1:8000/api/v1`. Keep
it as `127.0.0.1`, **not** `localhost` — with Docker Desktop/WSL2 installed,
`localhost` can resolve to `::1` and Windows forwards that into WSL instead of
this backend, producing a CORS error with no useful detail.

### Terminal 3 — Widget (only if you're working on the widget itself)

```powershell
cd "C:\Projects\My project\widget"
npm run dev
```

The dev harness needs an agent's public key as a query param:

```
http://localhost:5173/?agentKey=<public_key>&apiBase=http://127.0.0.1:8000/api/v1
```

Get `<public_key>` by creating an agent in the dashboard first (see below).

---

## First run: what to actually click

Same flow either way — just use `http://localhost:8080` for Docker or
`http://localhost:3000` for local dev.

1. Open the dashboard → **Sign up** (creates your tenant + owner account).
2. Create an **agent**.
3. **Activate** it.
4. Copy the agent's **embed snippet** — it looks like:
   `<script src="…/widget.js" data-agent-key="…" async></script>`
5. Paste that into any HTML page to see the floating widget, or use the widget
   dev harness URL above.
6. Chat with it. Voice needs a mic permission grant in the browser.

**Add the origin you're testing from to the agent's allowlist**, or the public
widget API rejects it — the widget endpoints use a per-agent origin allowlist,
separate from the dashboard's `DASHBOARD_CORS_ORIGINS`.

---

## Ports on this machine

| Port | What's on it |
|---|---|
| 80 | **Taken by Windows IIS** — not this project |
| 3000 | Dashboard (local dev) |
| 5173 | Widget dev harness |
| 5432 | Native PostgreSQL install (used by local dev) |
| 5433 | Docker's PostgreSQL (used by the Docker stack) |
| 8000 | Backend (local dev) |
| 8080 | nginx → the whole Docker stack |

---

## Tests, lint, typecheck

```powershell
# Backend (231 tests, no database needed)
cd "C:\Projects\My project\backend"
.\.venv\Scripts\python.exe -m pytest

# Dashboard
cd "C:\Projects\My project\dashboard"
npm test
npx tsc --noEmit
npm run lint

# Widget
cd "C:\Projects\My project\widget"
npm test
npm run typecheck
npm run lint
npm run build      # emits dist/widget.js
```

## Migrations (when you change a model)

```powershell
cd "C:\Projects\My project\backend"
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1     # undo the last one
```

Always read a generated migration before applying it — autogenerate does not
detect renames, it emits a drop + add, which loses data.

---

## Troubleshooting

**`docker` commands fail with a daemon/pipe error** — Docker Desktop isn't
running. Start it and wait for the whale icon to go steady.

**Port 80 is already allocated** — that's IIS. The override file already moves
nginx to 8080, so use http://localhost:8080. Don't delete that override.

**Dashboard loads but every API call fails (local dev)** — check the backend
terminal is actually up on 8000, and that `dashboard/.env.local` says
`127.0.0.1`, not `localhost`. Restart `npm run dev` after editing it — Next.js
reads env files at startup.

**"My signup disappeared"** — you probably switched between Way A and Way B.
They use two separate databases (5433 vs 5432).

**First chat or document upload hangs for a few seconds** — the ~90MB
embedding model is downloading from Hugging Face on first use, then it's
cached in `backend/.voice_models`.

**Chat replies come back as an error event** — a provider key is missing or out
of quota. Typed chat goes to Groq (`GROQ_API_KEY`) with Gemini
(`GEMINI_API_KEY`) as fallback; voice uses Groq for STT and Fish Audio
(`FISH_AUDIO_API_KEY`) for TTS. All three are set in `backend/.env` on this
machine.

**Billing / subscription pages don't work** — expected. The `DODO_*` variables
aren't set in `backend/.env` (they're all optional in `app/core/config.py`).
Add Dodo Payments test-mode keys from https://app.dodopayments.com if you need
that part.

**Password reset emails don't arrive** — if `RESEND_API_KEY` is blank the reset
link is written to the backend log instead of emailed. It's set here, so real
emails should send.
