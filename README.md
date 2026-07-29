# Voice Agent Platform

A SaaS platform where customers embed an AI voice + text agent on their own
website with a single `<script>` tag.

```
┌─ Customer's website ─┐      ┌─ This platform ────────────────────────┐
│  <script src=...>    │─────▶│  Public API   →  Chat/RAG  →  Claude   │
│  floating widget     │◀─────│  (per-agent origin allowlist)          │
└──────────────────────┘      │                                        │
                              │  Dashboard API  ←  Next.js dashboard   │
                              │  PostgreSQL                            │
                              └────────────────────────────────────────┘
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI API, database models, migrations |
| `widget/` | Embeddable browser widget *(Step 6)* |
| `dashboard/` | Next.js customer dashboard *(Step 8)* |

## Backend — local setup

Requires Python 3.11+ and a running PostgreSQL 14+ (18 recommended).

```powershell
cd backend

# 1. Virtual environment
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
#    This pulls in sentence-transformers + torch (CPU-only) for local RAG
#    embeddings — a large, slow install (multiple minutes). The embedding
#    model itself (~90MB) downloads from Hugging Face on first use and is
#    then cached; the first document you ingest or first chat message on a
#    knowledge-base-enabled agent will pause for a few seconds while that
#    happens.

# 2. Configuration
Copy-Item .env.example .env
#    Then edit .env: set DATABASE_URL credentials and generate a SECRET_KEY with
#    .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"

# 3. Databases
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -f scripts/bootstrap_db.sql

# 4. Migrations
.\.venv\Scripts\alembic.exe upgrade head

# 5. Run
.\.venv\Scripts\uvicorn.exe app.main:app --reload
```

API docs at http://127.0.0.1:8000/docs (local/test environments only).

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

The current suite runs without a database — health checks use dependency
overrides, and the rest are unit tests over config, security, and model
metadata.

### Migrations

```powershell
.\.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
```

Always read a generated migration before applying it. Autogenerate does not
detect table or column renames — it emits a drop plus an add, which loses data.

## API surface (v1)

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/health`, `/health/ready` | — | Liveness / readiness |
| `POST` | `/auth/signup` | — | Creates a tenant + its owner; returns a token pair |
| `POST` | `/auth/login` | — | Locks out after 10 failures for 15 min |
| `POST` | `/auth/refresh` | refresh token | Rotates; reuse revokes the whole family |
| `POST` | `/auth/logout` | refresh token | Revokes one session |
| `POST` | `/auth/logout-all` | access token | Revokes every session |
| `GET` | `/auth/me` | access token | Current user + tenant |
| `GET`/`POST` | `/agents` | access token | Read: any role. Create: owner/admin |
| `GET`/`PATCH`/`DELETE` | `/agents/{id}` | access token | Write: owner/admin |
| `GET`/`POST` | `/agents/{agent_id}/documents` | access token | List / add a document (pasted text or URL). Read: any role. Write: owner/admin |
| `POST` | `/agents/{agent_id}/documents/upload` | access token | Add a document from a `.txt`/`.md`/`.pdf` file upload |
| `GET`/`DELETE` | `/agents/{agent_id}/documents/{id}` | access token | Fetch / delete one document (cascades to its chunks) |
| `GET` | `/public/agents/{public_key}/config` | origin allowlist | Widget bootstrap (name, greeting, theme) |
| `POST` | `/public/agents/{public_key}/sessions` | origin allowlist | Issues a widget session token |
| `GET` | `/public/sessions/me` | widget session token | Validate a cached session token |
| `POST` | `/public/conversations` | widget session token | Starts a new chat thread |
| `GET` | `/public/conversations/{id}/messages` | widget session token | Full message history |
| `POST` | `/public/conversations/{id}/messages` | widget session token | Sends a message; streams the reply as SSE |

## Design decisions worth knowing

**Tenant isolation.** Every tenant-owned table carries `tenant_id` with
`ON DELETE CASCADE`. Queries must filter on it; from Step 2 that filtering is
enforced by a shared dependency rather than left to individual endpoints.

**Origin allowlisting, not secret keys.** An agent's `public_key` ships in the
customer's page source and is not a credential. Authorisation for the public
widget API is the agent's `allowed_origins` allowlist plus rate limiting. An
empty allowlist denies everything — an unconfigured agent is not embeddable.

**No `temperature`.** Current Claude models (Opus 5, Sonnet 5, Opus 4.7+)
reject `temperature`, `top_p`, and `top_k` with a 400. Agents store an
`effort` level (`low`…`max`), which is the supported control for reasoning
depth and token spend.

**One error shape.** Every failure, including unhandled exceptions, returns
`{"error": {"code": ..., "message": ...}}`. The widget runs on third-party
sites and cannot parse surprise HTML error pages.

**Relationships are `lazy="raise"`.** Accessing `tenant.agents` without an
explicit `selectinload`/`joinedload` raises instead of silently issuing a
query, so N+1 problems surface in tests rather than in production latency.

**Access tokens are JWTs; refresh tokens are not.** Access tokens are
stateless and short-lived (30 min). Refresh tokens are opaque random strings
stored as HMAC hashes, because they must be revocable the instant they rotate.
Rotation keeps a `family_id`; presenting an already-used token means it leaked,
so the whole family is revoked — logging out the legitimate holder too, which
is the correct response once a token is known to be compromised.

**Tenant scoping comes from the token, never the request.** Endpoints depend on
`TenantId`, derived from the authenticated user. No route accepts a tenant id
from a path or body, so there is no code path where a client can name someone
else's tenant. Cross-tenant reads return 404 rather than 403 — a 403 would
confirm the id exists.

**Some writes must survive a failed request.** `get_db` rolls back when a
request raises, which is right for ordinary handlers but wrong for security
side effects: a failed-login counter and a token-family revocation both happen
on the path to a 401. Those two call sites commit explicitly before raising.
The test harness's `get_db` override mirrors production commit/rollback
semantics precisely so this class of bug cannot hide again.

**The widget API is authorized by origin, not by secret — and that has a real
limit.** A browser cannot forge its `Origin` header, so the allowlist check
genuinely stops an agent from being embedded on an unauthorized website. It
does **not** stop a non-browser script that already has the `public_key`
(which is not secret — it's in page source) from calling the API directly
with a forged `Origin` header. The mitigations at this stage are per-agent
rate limiting and the tenant's `monthly_message_quota` (enforced starting in
the chat pipeline, Step 4) — not a substitute for real bot/abuse defenses
(WAF, CAPTCHA, anomaly detection), which are Step 9/10 territory once there's
real traffic to tune them against.

**One CORS middleware, not two.** The public widget API needs a per-agent,
database-backed origin allowlist; the dashboard API needs one static
allowlist. The tempting design — Starlette's built-in `CORSMiddleware` for the
dashboard, plus a custom middleware wrapping it for the public routes — is
broken: `CORSMiddleware` intercepts *any* OPTIONS preflight carrying
`Access-Control-Request-Method`, from *any* path, before it reaches the router
or an enclosing middleware's own logic, and answers it from its own static
list. That silently breaks every widget preflight in any environment with
dashboard CORS configured — which is every real deployment, just not the
default test environment (`tests/conftest.py` sets
`DASHBOARD_CORS_ORIGINS=""`, which skips adding the middleware entirely, so
the interaction never showed up in the unit suite — only in a live smoke
test against a real running server). `CorsMiddleware` in
`app/core/middleware.py` is the single owner of both policies for exactly
this reason.

**Public CORS preflight goes through real dependencies, not a database call
in middleware.** An earlier version of the public-route preflight handling
opened its own ad-hoc database connection directly in middleware, bypassing
FastAPI's dependency injection. That failed two ways: it couldn't see the
test harness's in-progress transaction (agents created mid-test were
invisible to it), and on Windows, reusing a connection pool across pytest's
per-test event loops corrupted asyncpg's transport state outright. The fix
was architectural, not defensive — explicit `@router.options(...)` handlers
in `app/api/v1/public.py` run the exact same `resolve_public_agent`
dependency as the real request, so preflight is byte-for-byte the same code
path: automatically test-override-safe and always on the correct event loop.

**No `temperature` here either — `effort` flows straight through.** The chat
pipeline calls Claude with `output_config={"effort": agent.effort}` and no
`temperature`/`top_p`/`top_k` at all, matching the model schema decision from
Step 1. `thinking` is left unset (Claude Opus 5 defaults to adaptive thinking
on its own); streaming uses the SDK's `stream.text_stream`, which yields text
content only — thinking-block deltas never reach the widget.

**Quota is consumed before calling Claude, with no refund on failure.**
Because origin allowlisting can't stop a scripted client with a valid
`public_key` from forging requests (see above), the quota counter has to
reflect attempted usage, not just successful usage — otherwise a client could
bypass it by triggering (and abandoning) failing calls. The row is locked
(`SELECT ... FOR UPDATE`) only for the increment itself, not for the whole
Claude call, so a busy tenant's other agents/visitors aren't serialized
behind one slow response.

**A failed Claude call must not corrupt the next turn's history.** The
user's message is persisted and committed *before* calling Claude, so it
survives a failed call — but that leaves a lone unanswered user message in
the conversation. The Claude API rejects non-alternating roles outright, so
the next user message would 400 the following turn if sent naively.
`_build_claude_messages` in `app/services/chat.py` collapses consecutive
same-role rows into one API turn, so a prior failure never breaks the next
message — covered by a dedicated test that deliberately fails a turn first.

**Streaming is verified over a real socket, not just in-process.** A live
smoke test using `curl --trace-time` against a real running uvicorn process
confirmed genuine incremental delivery (chunks arriving ~500ms apart,
matching injected delays) through this exact middleware stack. The obvious
in-process equivalent — httpx's `ASGITransport`, used everywhere else in the
test suite — turned out to coalesce a `StreamingResponse`'s body before
handing it to `.aiter_bytes()`, producing a false "it's buffered!" signal
even though the real server streams correctly. The permanent regression test
(`test_response_streams_incrementally_not_all_at_once`) works around this by
running a real `uvicorn.Server` on a real loopback socket, in-process, so a
future change that actually breaks streaming (e.g. swapping out
`BaseHTTPMiddleware`) still gets caught by the automated suite.

**The Anthropic client is a single mockable seam.** `app.services.llm.get_anthropic_client()`
is the *only* place `AsyncAnthropic(...)` gets constructed. Tests monkeypatch
this one function to a fake client shaped like the real SDK's stream object
(`text_stream` + `get_final_message()`); production code is never touched.
This was also verified against the *real* SDK, not just the fake: a live
request with no `ANTHROPIC_API_KEY` configured produced the real SDK's actual
`TypeError` ("Could not resolve authentication method..."), which
`stream_turn`'s broad exception handler caught and turned into a clean SSE
error event — logged server-side with a full traceback and request-id
correlation, never a 500 or a crash.

**Known limitation: no prompt caching yet.** `system_prompt` is sent as a
plain string on every turn, not wrapped in a `cache_control` block. For a
long multi-turn conversation this resends (and re-bills) the full system
prompt every time. Deliberately deferred — Anthropic's prompt-caching
semantics (breakpoints, TTL, the 20-block lookback window) are real
complexity worth its own focused pass rather than folding into an
already-large step. Revisit as a cost optimization once there's real traffic.

## RAG (Step 5)

**No pgvector — Python-computed cosine similarity instead, by deliberate
choice.** pgvector isn't installed on this Postgres instance, and it's a
compiled C extension I can't install myself here (no MSVC/gcc present, and
the installer's Stack Builder needs manual GUI interaction). Embeddings are
stored as a plain Postgres float array (`ARRAY(Float)`); retrieval loads an
agent's chunks and ranks them with a single vectorized numpy dot product
(`app/services/retrieval.py`). Embeddings are L2-normalized at creation time
specifically so that dot product *is* cosine similarity — no renormalizing
at query time. Fine at MVP scale (a few thousand 384-dim vectors is a few MB
and a sub-50ms operation); the swap to a native `vector` column + HNSW index
if pgvector is added later touches only that one function, nothing else in
the pipeline.

**Local embeddings, not a hosted API — also a deliberate choice, not a
default.** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) runs on
CPU, no API key, no per-token cost. `app/services/embeddings.py` is the one
mockable seam (`embed_texts`/`embed_query`), matching the pattern already
established for the Anthropic client — tests monkeypatch it with
deterministic vectors; one dedicated test (`test_embeddings.py`) uses the
*real* model to prove the actual production path (config → model load →
encode → normalize) produces sensible results, e.g. that a question about
business hours scores closer to an answer about business hours than to an
unrelated sentence about a recipe. `encode()` is CPU-bound, so both
functions run it via `asyncio.to_thread` — calling it directly from an async
handler would block the event loop for every other in-flight request for
however long encoding takes.

**Ingestion is synchronous within the request, bounded by hard caps — not
backgrounded.** Uploading a document chunks, embeds, and persists before the
response returns. This was a deliberate simplification: a `BackgroundTasks`-
based design was considered, but making a background job see the same
database state as the test harness's per-test transaction requires manually
driving the app's `get_db` dependency-override generator — real, working,
but meaningfully more failure-prone than reusing the request-scoped session
directly (the same class of lifecycle assumption that already caused two
bugs earlier in this project). `Document.status` (`pending`/`processing`/
`ready`/`failed`) still exists as a real column, not a placeholder, so moving
to a background job later is a code change, not a schema change. Worst-case
request latency is bounded by `max_pasted_text_chars` (200k), 
`max_upload_file_bytes` (5MB), and `url_fetch_timeout_seconds`/
`max_url_response_bytes` for URL ingestion — generous for a support knowledge
base, not for ingesting whole books in one document.

**URL ingestion fetches one page, not a crawler.** One URL in, one Document
out — extracts visible text via BeautifulSoup, using the page's `<title>` if
none was supplied. Adding more pages means adding more URLs, one at a time.
The response body is capped by actually counting bytes as they stream in,
not by trusting a `Content-Length` header a server could lie about or omit.

**Retrieval is skipped entirely for an agent with no knowledge base yet.**
`agent_has_chunks()` is a cheap existence check run *before* embedding the
user's message — the common case (a newly created agent) never pays even a
local CPU embedding call for a query that has nothing to compare against.

**Citations are a point-in-time record, not a live reference.** Stored as
denormalized `{"document_id", "title"}` JSON on the assistant `Message` row,
capturing what the document was titled *at the moment it answered a
question* — deliberately not re-derived via a join at read time, the same
way a citation in a paper doesn't retroactively update if the cited work is
later renamed.

**Verified against real components, not just fakes.** Chunking, the
sentence-transformers model, and full document ingestion were each verified
live: a hand-crafted (but genuinely valid — confirmed against pypdf
directly) PDF proves real PDF extraction works, not a mock of the library;
a live server ingested a real return-policy document with the real
embedding model and the resulting system prompt sent to Claude — visible in
the request-debug log, the same mechanism that caught Step 4's
missing-API-key path — correctly included the retrieved excerpt for a
question that never mentioned the document by name ("How many days do I
have to return something?" correctly matched a chunk about a 45-day return
window on semantic similarity, not keyword overlap).

**A real chunking bug, caught by testing the full round-trip, not just the
happy path.** The first version of the sliding-window chunker snapped a
chunk's *end* to the nearest word boundary but never checked where the
*next* chunk's start landed — the fixed step from the previous start could
land mid-word, producing fragments like `"rd24"` instead of `"word24"`. The
fix (snap the start forward too) then introduced a *worse* bug: for a
single long unbroken token with no space anywhere ahead (e.g. a URL), the
forward search for a boundary found none and jumped to the end of the text,
silently discarding everything in between. The final fix bounds that search
to one `chunk_size` — same distance the end-snapping logic already accepts
before giving up and hard-cutting. Both failure modes have dedicated
regression tests.

### Testing

DB-backed tests run against `voiceagent_test`, which the suite refuses to skip:
the database name must end in `_test` or collection aborts. Each test runs
inside an outer transaction with `join_transaction_mode="create_savepoint"`, so
application-level `commit()` calls behave normally but nothing reaches disk.

The default test environment sets `DASHBOARD_CORS_ORIGINS=""`, which does not
match production. `test_public.py` includes a dedicated regression test that
builds an app with dashboard CORS actually configured to catch interaction
bugs the default environment would hide — see the CORS design note above.
