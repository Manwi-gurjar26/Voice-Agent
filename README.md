# Voice Agent Platform

A SaaS platform where customers embed an AI voice + text agent on their own
website with a single `<script>` tag.

```
┌─ Customer's website ─┐      ┌─ This platform ────────────────────────┐
│  <script src=...>    │─────▶│  Public API   →  Chat/RAG  →  Gemini   │
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

**No `temperature`.** Agents store an `effort` level (`low`…`max`) instead,
which maps to Gemini's `thinking_config.thinking_budget` (a token count) —
one reasoning-depth/token-spend knob per agent, not three separate ones.

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

**No `temperature` here either — `effort` flows straight through as a
thinking budget.** The chat pipeline calls Gemini with
`thinking_config=ThinkingConfig(thinking_budget=N)`, where N is looked up
from `agent.effort` via a small fixed table in `app/services/chat.py`
(`low`→128 … `max`→24576) — no `temperature`/`top_p`/`top_k` at all. 128
(not 0) is the floor for `low` because gemini-2.5-pro can't fully disable
thinking the way flash can; this keeps `low` safe regardless of which Gemini
model an agent is configured with. Streaming uses the SDK's
`generate_content_stream`, iterating chunks' `.text` — thinking-token deltas
never reach the widget.

**Quota is consumed before calling Gemini, with no refund on failure.**
Because origin allowlisting can't stop a scripted client with a valid
`public_key` from forging requests (see above), the quota counter has to
reflect attempted usage, not just successful usage — otherwise a client could
bypass it by triggering (and abandoning) failing calls. The row is locked
(`SELECT ... FOR UPDATE`) only for the increment itself, not for the whole
Gemini call, so a busy tenant's other agents/visitors aren't serialized
behind one slow response.

**A failed Gemini call must not corrupt the next turn's history.** The
user's message is persisted and committed *before* calling Gemini, so it
survives a failed call — but that leaves a lone unanswered user message in
the conversation. Gemini's API rejects non-alternating roles outright, so
the next user message would error the following turn if sent naively.
`_build_gemini_contents` in `app/services/chat.py` collapses consecutive
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

**The Gemini client is a single mockable seam.** `app.services.llm.get_gemini_client()`
is the *only* place `genai.Client(...)` gets constructed. Tests monkeypatch
this one function to a fake client shaped like the real SDK's `aio.models`
resource (`generate_content_stream` + `generate_content`); production code
is never touched. This was also verified against the *real* SDK, not just
the fake: `genai.Client(api_key=None)` (or an empty string) raises a `ValueError`
("No API key was provided...") **immediately at construction**, unlike
Anthropic's client, which only fails on the first real request. Since
`get_gemini_client()` is called from inside `stream_turn`/`complete_turn`'s
existing broad exception handler, that construction-time `ValueError` lands
in exactly the same place a request-time failure would — a clean SSE `error`
event or `AppError`, never a 500 or a crash, with a full traceback logged
server-side.

**Originally Claude, swapped to Gemini for cost, not capability.** The chat
pipeline was first built against Anthropic's Claude. It was swapped to
Google Gemini because this project cannot take on any paid API cost, and
unlike Claude, Gemini has a genuinely free tier (Google AI Studio, no card
required) — sufficient for testing with real early users before any billing
is turned on. `EffortLevel` (`low`…`max`), the streaming-vs-non-streaming
split, `_prepare_turn`'s quota/retrieval/history-building sequence, and the
whole client-seam pattern all carried over unchanged; only the request/
response shape talking to the provider changed (see `app/services/chat.py`
and `app/services/llm.py`). This is the one dependency in the whole platform
still requiring a real (if free) API key — see the chat pipeline's own
setup note for how to get one.

**Known limitation: no prompt caching yet.** `system_prompt` is sent as a
plain string on every turn, not wrapped in a cached-content block. For a
long multi-turn conversation this resends the full system prompt every time.
Deliberately deferred — implicit/explicit caching semantics are real
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
established for the Gemini client — tests monkeypatch it with
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
embedding model and the resulting system prompt sent to the LLM — visible in
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

## Widget (Step 6)

A Preact widget that ships as a single `<script>` tag and floats a chat UI
over the host page.

```powershell
cd widget
npm install
npm run dev        # dev harness at http://localhost:5173/?agentKey=...&apiBase=...
npm run build       # tsc --noEmit, then emits dist/widget.js
npm test            # vitest run
npm run typecheck
npm run lint
```

**Ships as one file, no module system assumed.** `vite.config.ts` builds in
library mode with a single IIFE output (`dist/widget.js`) — no code
splitting, no ESM. The result is 26.98 kB raw / **10.42 kB gzipped**, under
the ~15KB gzip budget, and defines nothing on `window`: `main.tsx` has no
exports, so Rollup's IIFE wrapper has nothing to attach globally. The embed
snippet is exactly what `AgentRead.embed_snippet` (`app/schemas/agent.py`)
generates: `<script src="{widget_cdn_url}" data-agent-key="{public_key}"
async></script>`. The dev harness (`widget/index.html`, never shipped)
substitutes `?agentKey=`/`?apiBase=` query params for those two data
attributes.

**Shadow DOM isolation, both directions.** The widget mounts into a host
`<div>` with `style.all = "initial"` and an open shadow root, so the host
page's global CSS can't leak in and the widget's own styles (`styles.css`,
inlined via `?inline` and injected as a `<style>` inside the shadow root)
can't leak out. Runtime theming (`primaryColor`, `bubbleRadius`, fetched from
the agent's public config) is applied as CSS custom properties on the shadow
root, not inline styles per element.

**Hand-rolled SSE parsing, not `EventSource`.** The message-send request is a
`POST` with a JSON body and an `Authorization` header — native `EventSource`
only supports `GET` with no custom headers. `sse.ts` parses `event:`/`data:`
blocks out of a `fetch()` `ReadableStream` directly, buffering across
`reader.read()` chunk boundaries (`event: X\ndata: {...}\n\n`, matching
`app/services/chat.py`'s `_sse()` helper byte-for-byte). Verified with a test
suite that deliberately splits the same payload at arbitrary byte offsets,
including exactly at the `\n\n` separator and one-character-at-a-time.

**Session/conversation persistence uses `sessionStorage`, not
`localStorage`.** A widget session already expires server-side after
`widget_session_expire_minutes`; surviving a full browser restart would
outlive what the token is good for anyway, and `sessionStorage` clears
naturally when the tab closes. Storage keys are namespaced per
`public_key`, every read/write is wrapped in try/catch (private browsing and
storage-restricted iframes can throw — persistence degrading to "start
fresh" is fine, a crash isn't), and a locally-expired token is rejected
before even attempting server-side validation. If a session dies mid-visit
(the 60-minute expiry is real for a tab left open), `useChat` refreshes it
and retries the send exactly once, transparently — most visitors should
never see "please refresh the page" just because they were reading for a
while before typing.

**Testing.** 60 tests across seven files (`npm test`): `sse.ts` (chunk-
boundary edge cases), `api.ts` (mocked `fetch`, one test per endpoint plus
error-envelope parsing), `storage.ts` (including sessionStorage-throws
edge cases), `hooks/useChat.ts` (the state machine, against a fake
`ApiClient` — bootstrap, session resume/refresh, streaming sends, the
auth-error retry-once path, error-code-to-message mapping), and
component/integration tests (`Composer`, `MessageBubble`, `App`) via
`@testing-library/preact` covering open/close, typing and sending, streamed
text arriving in the DOM, and the error banner.

**Verified against a real running backend, with a caveat.** A tenant, agent,
and origin allowlist (`http://localhost:5173`, the Vite dev server's origin)
were created via the live dashboard API against a real Postgres instance,
then exercised end-to-end with `curl` using the exact request shapes
`api.ts` sends: CORS preflight (`OPTIONS`), session creation, session
validation, conversation creation, sending a message and reading the SSE
response, listing message history, and both an allowed and a rejected
`Origin`. Every response matched what `types.ts` and `sse.ts` expect
byte-for-byte, including the graceful `event: error` /
`{"code": "llm_error", ...}` path with no LLM API key configured — the same
failure mode already covered by the backend's own live-server tests. (This
pass predates the Claude → Gemini swap; the specific missing-key exception
type changed — see the chat-pipeline section above — but the resulting
clean-SSE-error behavior this test actually checks did not, since both land
in the same broad exception handler.)

**Update: the real-browser gap above is now closed.** Playwright (Chromium,
installed fresh into a scratch npm project — no admin rights or Docker
needed) drove an actual browser against the real backend/Postgres/dashboard
dev server: created a tenant via the dashboard signup form, created and
activated an agent with `allowed_origins` set to the widget dev server's
origin, extracted the real `public_key` from the rendered `embed_snippet`,
then loaded the widget dev harness pointed at that agent. Playwright's
selector engine pierces open shadow roots automatically, so no special
handling was needed to find `.va-launcher` inside the widget's shadow DOM.
Confirmed in the real DOM, with screenshots: the launcher mounts and renders
correctly on a simulated host page, clicking it opens the panel with the
agent's real greeting, a typed message sends and appears as a user bubble,
and — since this environment had no billed LLM API key at the time — the
same missing-key error seen in backend logs surfaced exactly as the widget's
`ErrorBanner` component ("The assistant is temporarily unavailable...")
rather than a broken UI or a hang. (This pass predates the Claude → Gemini
swap; not yet re-run against Gemini specifically.) What's still not covered
by this pass: voice/mic (`getUserMedia` in a headless browser is its own can
of worms) and a genuine successful LLM reply rendering and streaming into
the DOM (blocked on the same missing-API-key gap as Step 7's live voice
verification). The jsdom-based `App.test.tsx`
suite continues to cover the full open → type → send → stream →
error-banner flow at the component level, now corroborated rather than
merely inferred by this real-browser run.

**`npm audit` disclosure.** 10 findings (3 moderate, 6 high, 1 critical),
all confined to dev-only tooling never present in the shipped `widget.js`:
a `brace-expansion` ReDoS reachable only through eslint's `minimatch`
dependency chain; a `vite`/`vite-node` path-traversal and dev-server issue
reachable only while `vite dev`/`vitest` themselves are running; and a
critical "arbitrary file read" in `vitest`'s optional UI server, which
applies only to `vitest --ui` — never run in this project. `npm audit fix
--force` was deliberately not run: it would force major breaking upgrades
(eslint 9→10, vitest 2→4) without vetting compatibility, to close
vulnerabilities that don't affect the production artifact. Revisit when
next touching devDependencies.

## Voice (Step 7)

Speech in, speech out — a mic button in the widget's composer (shown when an
agent has `voice_enabled=true`), wired to real STT/TTS. This is turn-based,
not a live open-mic phone call: record → transcribe → run the same chat
pipeline as typed messages → speak the reply. A continuously-listening,
interruptible voice call (streaming STT, voice-activity detection, barge-in)
is a materially larger effort and was deliberately left out of this step.

**Update: swapped to fully local, free STT/TTS — no API key, no billing,
ever.** Originally OpenAI (Whisper for STT, `tts-1` for TTS). Voice is
otherwise the one feature in this whole platform that structurally requires
a paid, metered API, and this project cannot take on any billing — so
`app/services/voice.py` now runs `faster-whisper` (a CTranslate2-based local
Whisper implementation) for STT and Piper (a fast local neural TTS engine)
for TTS, both entirely on CPU with zero network calls after their model
files are cached once. This is not a new architectural idea for this
codebase — it's the exact pattern `app/services/embeddings.py` already used
for RAG in Step 5 (a local `sentence-transformers` model instead of a hosted
API), just applied to voice. `Agent.voice_id` is now validated against a
small set of real Piper voice names (`ALLOWED_VOICE_IDS` in
`app/schemas/agent.py`) — `en_US-lessac-medium`, `en_US-amy-medium`,
`en_US-ryan-medium`, `en_GB-alan-medium` — each individually confirmed
downloadable before being added, not assumed from Piper's voice list.

**A real client-object seam, unlike the old OpenAI code's shared one.**
`voice.py` now has two independent seams, `get_whisper_model()` and
`get_piper_voice(voice_id)`, rather than one shared client — STT and TTS are
two unrelated local models with no client object in common, unlike OpenAI's
single `AsyncOpenAI` instance serving both. Both are lazily constructed and
cached (Piper per voice ID, since an agent can pick any of the four), and
both wrap model construction in a try/except that raises
`VoiceUnavailableError` — the local equivalent of the old "no API key
configured" condition, now covering a genuinely different failure mode (a
cold cache with no internet on first run) rather than a missing credential.

**Decoding is format-agnostic, unlike the old filename-hint approach.**
OpenAI's transcription API used the uploaded filename's extension as a
format hint; faster-whisper instead decodes directly from a byte stream via
PyAV (bundled ffmpeg, no system dependency to install), so `transcribe_audio`
no longer takes or needs a `filename` argument at all — confirmed against
the *exact* format the widget really sends, not assumed: a WAV file was
re-encoded to WebM/Opus with PyAV by hand (matching `voiceCapture.ts`'s real
`MediaRecorder` output) and decoded correctly straight from an in-memory
`BytesIO`, no temp file.

**The voice endpoint reuses the text pipeline's guts, not a parallel one.**
`chat_service.stream_turn` (SSE, for typed messages) and the new
`chat_service.complete_turn` (a plain JSON response, for voice — TTS needs
the full reply text before it can run, so there's nothing to stream) both
delegate the identical quota-check → persist-user-message → retrieval →
build-Gemini-contents sequence to a shared `_prepare_turn` helper. Only the
Gemini call itself and how the result is returned differ. A spoken turn gets
the exact same RAG augmentation, quota accounting, and conversation history
handling as a typed one, for free.

**A Step 6 CORS gap, fixed here.** While wiring up the new
`/conversations/{id}/voice-messages` route, it turned out **none** of
`public_chat.py`'s routes — including the pre-existing `/conversations` and
`/conversations/{id}/messages` from Step 6 — had a registered `OPTIONS`
handler. A real browser's CORS preflight for any of them would have failed
outright (curl, used for Step 6's live verification, doesn't preflight, so
this was never exercised). Fixed by adding the same kind of
dependency-free `OPTIONS` handler `public.py`'s `/sessions/me` already uses
for paths with no `{public_key}` segment, covering all three routes.

**A TTS failure degrades to a silent reply, not a lost one.** By the time
`synthesize_speech` runs, the assistant's text reply is already persisted
(and quota already consumed, same unconditional-consumption policy as text
messages — see Step 5/6 notes above). If the TTS call itself then fails, the
endpoint still returns the transcript and text reply with `audio_base64: ""`
rather than raising and discarding a reply that actually succeeded; the
widget shows the text and simply doesn't play anything back.

**Recording is a widget-owned concern, not bolted onto the chat hook.**
`voiceCapture.ts`'s `VoiceRecorder` wraps `getUserMedia`/`MediaRecorder`
entirely on its own (mimeType negotiation across browsers — Safari needs
`audio/mp4`, everything else prefers `audio/webm;codecs=opus` — a 120-second
hard cap, and mic-track cleanup on every exit path). Its `completion`
promise resolves the same way whether a recording ends via a manual stop, the
120s cap, or a cancellation, which is what lets `MicButton` auto-finalize a
capped recording without the user having to tap stop again. `useChat`'s new
`sendVoiceMessage` only ever receives a finished `Blob` — it has no idea
`MediaRecorder` exists, and reuses the exact same session-expiry
retry-once-then-friendly-banner logic (`withSessionRetry`, factored out of
what was previously `sendMessage`-only code) as typed messages.

**Testing.** Backend: 14 tests (`test_voice.py`) covering the happy path,
`voice_enabled=false` rejection, oversized uploads, empty transcripts,
transcription/LLM/TTS failures, quota exhaustion, missing/wrong session or
origin, and the preflight route — `get_whisper_model`/`get_piper_voice`
faked at their seams, no real model load needed to run these, matching the
existing `get_anthropic_client` fake-seam pattern. A dedicated
`test_voice_models.py` (1 test, mirroring `test_embeddings.py`'s role for
the RAG embedding model) runs the *real* Whisper and Piper models with no
mocking at all — full suite now 230 tests. Widget: unchanged by this swap
(27 pre-existing voice tests still pass) — the widget only ever dealt with
recording and playing back audio, never which provider transcribed or
synthesized it; `audio_mime` in its test fixtures was updated from
`audio/mpeg` to `audio/wav` for accuracy, not because any widget logic
changed (`decodeAudioToUrl` already builds its `Blob` from whatever mime the
backend sends, with no format-specific branching).

**Live verification: complete for what this swap actually owns, honestly
partial for what it doesn't.** `test_voice_models.py` proves the core claim
for free: real Piper-synthesized speech, decoded by real faster-whisper, at
CPU speed, no network calls, matching "What can you help me with today?"
back exactly. Beyond the automated suite, a real signed-up tenant, a real
voice-enabled agent (`voice_id: en_US-lessac-medium`), and a real recording
of "What are your business hours?" were sent through the actual running
`/voice-messages` endpoint against a live server — the backend log shows
`faster_whisper: Detected language 'en' with probability 0.99` and the
exact transcribed text reaching the LLM request payload, byte for byte. That
request then failed with the same pre-existing `llm_error` documented in
Step 4/6 (no `GEMINI_API_KEY` configured in this environment at the time) —
a Step 4 dependency this swap never touched, not a new gap. **Voice's own
paid-API dependency is now fully eliminated and fully verified; a complete
spoken-question-to-spoken-answer demo still needs a working (free-tier)
Gemini key,** exactly as it would for a *typed* question, and for the same
reason.

## Dashboard (Step 8)

A Next.js app for signing up, logging in, and managing agents — the first
thing to actually consume the "Dashboard API" that's existed since Step 2.

```powershell
cd dashboard
npm install
npm run dev        # http://localhost:3000
npm run build
npm test            # vitest run
npx tsc --noEmit
npm run lint
```

**Client-side, calling FastAPI directly — not a BFF.** The backend already
had `DASHBOARD_CORS_ORIGINS` middleware set up specifically for a browser to
call it directly, and sets no cookies anywhere (`/auth/*` returns
`{access_token, refresh_token}` in a JSON body, full stop). Building a
Next.js proxy layer with httpOnly cookies would have been more secure
against XSS, but would leave that existing CORS support unused and add a
server-to-server networking layer the backend wasn't designed around.
Instead: tokens live in `localStorage` (`lib/auth-storage.ts`, mirroring
`widget/src/storage.ts`'s try/catch-everywhere shape), and `lib/api.ts` calls
the FastAPI backend directly from the browser. The tradeoff — tokens are
readable by any injected script — is deliberate and documented, not an
oversight.

**One retry-on-401 layer, not one per call site.** The widget only ever
needed session-refresh-and-retry in a single place (`useChat.sendMessage`).
The dashboard has eight authenticated endpoints across five pages, so
`lib/api.ts`'s `authedRequest` centralizes it instead: a local-expiry
precheck before the request (mirroring the widget's pre-check in
`storage.ts`), and a reactive refresh-and-retry-once on an actual 401 from
the server. Every page calls plain functions (`listAgents()`, `createAgent()`,
...) with no knowledge that a refresh can happen underneath.

**Route protection is client-side only.** Since there's no cookie for
Next.js middleware/proxy to read on the server, `app/(dashboard)/layout.tsx`
redirects to `/login` client-side based on `AuthProvider`'s bootstrapped
state, and `app/(auth)/layout.tsx` redirects an already-authenticated visitor
away from `/login`/`/signup`. An unauthenticated visitor briefly sees a
loading state before the redirect fires, rather than the protected page's
content — a direct consequence of the localStorage decision above, not a gap
in this step.

**Forms are hand-rolled with `react-hook-form` + `zod`, not shadcn's `Form`
wrapper.** The installed `shadcn` CLI version (`style: "base-nova"`, built on
`@base-ui/react` rather than Radix) postdates this project's knowledge base
enough that `npx shadcn add form` silently installed nothing, and its actual
current shape couldn't be verified. Rather than depend on an opaque
component, every form uses `useForm`/`Controller` directly against the
existing `Input`/`Select`/`Switch`/`Textarea` primitives — plain, verifiable
code instead of a black box. (Relatedly: this shadcn version's `Button`
doesn't support Radix-style `asChild` — it uses a `render` prop instead,
e.g. `<Button render={<Link href="..." />}>Label</Button>`.)

**The signup password policy isn't duplicated client-side.** `backend/app/schemas/auth.py`
owns the real policy (minimum length, mixed character classes); the signup
form only checks that a password was entered at all, and surfaces the
backend's actual `validation_error` message on failure via
`formatApiError()` (which unwraps `details.fields[].msg` — the generic
envelope message is just "The request payload is invalid.") rather than
reimplementing the policy and risking drift.

**Agent create vs. edit share one form, not two.** `AgentCreate` has no
`status` or `rate_limit_per_minute` field (every agent starts as `draft` at
`rate_limit_per_minute=30` server-side); `AgentUpdate` has both.
`components/agent-form.tsx` renders one shared field set plus those two
extra fields only in edit mode, converting to the right payload shape via
`formValuesToCreate`/`formValuesToUpdate` — one ~250-line component instead
of two 90%-identical ones.

**Testing.** Vitest + React Testing Library (matching the widget's stack).
47 tests: `lib/auth-storage.ts` (mirrors `storage.test.ts`, including the
storage-throws case), `lib/api.ts` (one test per endpoint, the
proactive-refresh and reactive-refresh-retry-once paths, error-envelope
parsing), `lib/auth-context.tsx` (bootstrap, login, signup, logout, a
stored-but-no-longer-valid session clearing itself), and page-level tests
for login, signup, the agent list (including the delete-confirm dialog), and
agent create/edit (including one-per-line origin parsing and the
create/update field-set difference above) — all against a mocked `lib/api`,
not a real backend.

**Live verification.** Real backend, real Postgres, real dashboard dev
server: signup, `/auth/me`, agent create (both with and without optional
fields, confirming server-side defaults apply when they're omitted), list,
update (status + rate limit), token refresh, delete, and both the CORS
preflight and the actual response headers for a cross-origin request from
`http://localhost:3000` — all via `curl` replicating the exact request
shapes `lib/api.ts` sends, the same rigor as Steps 6-7.

**Update: real click-through browser testing, now done.** The same
Playwright run described in Step 6's update also drives the dashboard
itself: a real signup form submission (with real client + server-side
validation), redirect to `/agents`, the agent-creation form, and the
`status` field's custom Base UI `Select` (opened and an option chosen via
Playwright's role-based locators — it's not a native `<select>`, so this
confirms the component is actually operable by something other than a
mocked RTL environment). Not covered in this pass: the login page,
the delete-agent confirmation dialog, and the billing page's Checkout
redirect flows (blocked on the same missing-billing-account gap as Step 9)
— the RTL component tests above are still the only coverage for those.

## Billing (Step 9)

Dodo Payments Checkout to upgrade, a webhook handler to keep `Tenant.plan`/
quota in sync with what Dodo reports, and a dashboard billing page.
`Tenant.plan` and `monthly_message_quota` have existed since Step 1 with
nothing to ever change them except a manual DB edit — this is what actually
wires them up. Scope, confirmed upfront: Checkout + webhook sync + a
dashboard page only. Dodo's own Customer Portal (linked from the dashboard)
handles cancel/downgrade/payment-method changes; no custom invoice UI,
proration, or usage-based pricing was built.

**Built against Dodo Payments, not Stripe — a hard block, not a preference.**
Stripe does not onboard new India-registered accounts, which made it
impossible to even get a test-mode key for this step on an India-based
account — a signup problem, not a missing-credit-card one (that category of
problem is what voice's original OpenAI billing gap was, before Step 7's
local-model swap eliminated it entirely). Dodo Payments is a
merchant-of-record gateway available to
India-based merchants, with the same free, unlimited test-mode guarantee as
Stripe's. The swap touched `app/services/billing.py`, the webhook handler
(renamed `webhooks_stripe.py` → `webhooks_dodo.py`), `Tenant`'s
`dodo_customer_id`/`dodo_subscription_id` columns (a real alembic rename
migration, verified upgrade → downgrade → upgrade against the live local
database, not just autogenerated and trusted), and `config.py`'s settings —
nothing in the dashboard's billing page or `lib/api.ts` needed to change,
since both already called generic `/billing/checkout-session` and
`/billing/portal-session` endpoints with no provider-specific wording.

**A real client-object seam, unlike the old Stripe code.** `llm.py`/
`voice.py` each hide a lazily-constructed client behind one function so
tests can monkeypatch it; Stripe's async methods took `api_key` per call
instead, so that file had no client object to seam. Dodo's Python SDK
(`AsyncDodoPayments`, confirmed against the actually-installed
`dodopayments` 1.109.0 by introspecting its real method signatures before
writing any code against it — not assumed from docs) is a real constructed
client, so `app/services/billing.py` now has a `get_dodo_client()` seam
matching the Gemini/local-voice-model client-seam pattern exactly. One
consequence: the
checkout/portal tests in `test_billing.py` monkeypatch a single function
instead of two separate Stripe resource classmethods — simpler, not just
different.

**No `StripeObject`-subclasses-`dict` gotcha here — verified, not assumed
absent.** Dodo's `Subscription` is a plain pydantic model; `subscription.customer.customer_id`,
`.product_id`, `.metadata` are all ordinary attribute access, confirmed by
constructing a real, fully schema-valid `Subscription` webhook payload,
hand-signing it with the real Standard Webhooks HMAC scheme, and running it
through the real `client.webhooks.unwrap()` — not a hand-wave that pydantic
"probably" behaves better than `StripeObject`.

**A real gotcha this integration *did* hit: the `[webhooks]` extra.**
`client.webhooks.unwrap()` raises `dodopayments.DodoPaymentsError` with the
message "You need to install `dodopayments[webhooks]` to use this method"
on the base package alone — caught by actually calling it in a Python shell
before writing the webhook handler, not discovered later in a bug report.
`requirements.txt` pins `dodopayments[webhooks]`, which pulls in
`standardwebhooks` (the HMAC verification library Dodo's SDK wraps); a bad
or forged signature raises `standardwebhooks.webhooks.WebhookVerificationError`,
confirmed the same way — by deliberately corrupting a real signed payload
and checking the exact exception type raised, not guessing at Dodo's error
hierarchy.

**A real simplification over Stripe's tenant-resolution split.** Stripe's
Checkout `Session` object only exists at checkout time, so the old webhook
handler needed two different tenant lookups: `client_reference_id`/
`metadata` on `checkout.session.completed`, versus `stripe_customer_id` on
every later subscription event. Dodo's `Subscription` object carries
`metadata` as one of its own persisted fields, present on *every*
subscription webhook — creation, renewal, cancellation, all of it — so
`webhooks_dodo.py`'s `_find_tenant()` is one metadata lookup with a
`dodo_customer_id` fallback, covering every event type below with no
per-event-type special case.

**Billing is owner-only, not owner-or-admin.** Every other write in this API
(`agents`, `documents`) allows owner **or** admin. Billing moves money, so
`app/api/deps.py` gained a new `RequireOwner` alongside the existing
`RequireAdmin` — a deliberately stricter bar than the precedent, not an
oversight. `create_checkout_session` now also takes the owner `User` object
(previously discarded as `_: RequireOwner`) — needed to pass a real
email/name to Dodo for a brand-new customer, since unlike Stripe, Dodo's
checkout session has no "leave customer unset, collect an email on the
hosted page" mode for a first-time payer.

**Calendar-aligned resets come from `subscription.renewed`, not
`subscription.updated`.** A subscription can update for reasons that have
nothing to do with a billing cycle renewing (a metadata change, a plan swap
mid-cycle) — resetting `messages_used_in_period` there would zero out usage
for the wrong reason. `subscription.renewed` fires specifically when a
billing cycle renews and is paid for, so that's the only handler that
touches the usage counter. `subscription.active` (the first-activation
event, doubling as what Stripe split across `checkout.session.completed` +
`customer.subscription.created`) syncs `plan`/`monthly_message_quota`/
`dodo_customer_id` and nothing else. The rolling 30-day window in
`app/services/quota.py` is otherwise untouched — it's still exactly correct
for a tenant that never subscribes.

**Plan-to-quota mapping lives in code, not settings.** `PLAN_QUOTAS` in
`app/services/billing.py` is a product decision (how much does each tier
get), versioned with the code. Product IDs, by contrast, are environment
config (`DODO_PRODUCT_ID_STARTER`/`_PRO`/`_ENTERPRISE`) — they're created in
the merchant's own Dodo dashboard and differ between test and live mode, so
they were never going to be hardcoded.

**Webhook state mutators take no db session and never call `commit()`.**
`app/db/session.py`'s `get_db` already commits at the end of every request;
`app/services/chat.py`'s explicit mid-request commits are the documented
exception, needed only because a subsequent step (the Gemini call) can fail
and the user's message must survive that. Nothing runs after
`apply_subscription_state`/`reset_usage_period`/`downgrade_to_free` in the
webhook handler, so there's nothing to protect against — they just mutate an
already-session-attached `Tenant` and let the request's own commit handle
the rest.

**Testing.** Backend: 18 tests (`test_billing.py`) — Checkout/Portal happy
paths, owner-only enforcement, unconfigured-Dodo and no-Dodo-customer-yet
error paths, and every subscription event type's state transition,
including a subscription with a product this app doesn't recognise (leaves
the plan untouched, logs a warning, doesn't crash), an event for a tenant
matching no metadata/customer (200, no-op), and a dedicated test for the
metadata-missing → customer-id-fallback path. Webhook signature tests
replicate Dodo's real Standard Webhooks HMAC scheme by hand
(`{id}.{timestamp}.{body}`, HMAC-SHA256, base64) and run through the real
`client.webhooks.unwrap()`, not a mocked verifier — a forged signature is
asserted to actually fail, not just assumed to. Full suite now 229 tests.
Dashboard: unchanged test *behavior* (56 tests still passing) — only the
mocked Checkout/Portal URLs in `lib/api.test.ts` and `billing/page.test.tsx`
needed updating, since the dashboard code itself was never Stripe-specific.

**Live verification: not yet performed against the real Dodo API, by
explicit choice — but the real SDK itself was exercised directly.**
Exercising Checkout/webhook end-to-end for real needs a Dodo test-mode
account (API key, webhook signing key, three test Product IDs) that wasn't
available this session. Unlike that gap, everything short of an actual
network call *was* verified against the real, installed `dodopayments`
package rather than assumed from documentation: every method signature
(`checkout_sessions.create`, `customers.customer_portal.create`,
`webhooks.unwrap`), every response field name (`checkout_url`, `link`), the
`[webhooks]` extra requirement, and the full sign → verify → parse round
trip for a webhook payload were each confirmed by actually calling the real
client in a Python shell before any implementation code was written. Set
the `DODO_*` variables in `backend/.env` to point at a running backend to
exercise the real Checkout/Portal/webhook flow end-to-end.

## Deployment (Step 10)

Closes out three TODOs that have been sitting in code comments since the
steps that wrote them, plus containerizes the whole stack.

```powershell
cp .env.example .env                    # POSTGRES_*, PUBLIC_ORIGIN
cp backend/.env.example backend/.env    # fill in real secrets
docker compose up --build
```

**Update: now actually built and run, end to end — and it caught a real bug
on the first attempt.** Docker Desktop was installed on the dev machine
(WSL2 backend; needed a BIOS-level virtualization flag flipped first) and
`docker compose up --build` was run for real. `postgres:18-alpine` refused
to start with the original config: recent `postgres` images require the
volume mounted at `/var/lib/postgresql` (the whole data root), not
`/var/lib/postgresql/data` as this file originally had it — the entrypoint
hard-errors instead of silently doing the wrong thing, which is exactly
why this was worth actually running rather than trusting the YAML review
below. Fixed in `docker-compose.yml`; confirmed with a clean `down -v` +
`up --build` that a fresh, empty volume now initializes correctly.

With that fixed, all five containers (`postgres`, `redis`, `backend`,
`dashboard`, `nginx`) came up and reported healthy, alembic ran every
migration from a blank database through nginx's own container network, and
a full request round-trip was exercised *through nginx* (not hitting any
container port directly): dashboard signup → agent creation → activation →
a real widget session → conversation → message send, returning the same
graceful `event: error` SSE payload as the local runs (still no
`GEMINI_API_KEY` configured on this machine at the time). `/widget.js`
served correctly from nginx's
static location block. Most importantly, the thing this step actually
exists for — Redis-backed, cross-worker rate limiting — was verified
against a **real** Redis container, not `fakeredis`: an agent's
`rate_limit_per_minute` was lowered to 3, and requests 1–3 returned `200`
while requests 4–5 returned `429` with `retry_after: 60`, exactly matching
`app/services/rate_limit.py`'s design. One environment-specific wrinkle,
not a project bug: this dev machine's port 80 is already bound by Windows'
own IIS (`W3SVC`/HTTP.sys), so verification used a throwaway Compose
override remapping nginx to port 8080 — deleted afterward, not part of the
committed config, and irrelevant to a real Linux deployment target where
port 80 is normally free.

**Rate limiting gets a Redis backend, selected by whether `REDIS_URL` is
set — not a rewrite.** `app/services/rate_limit.py`'s in-memory sliding
window (a deque per key, correct only within one process) was the whole
reason multi-worker deployment didn't work before. It's now one of two
backends behind the exact same `check()`/`_reset_for_tests()` functions
every call site already used — `app/api/public_deps.py` didn't change at
all. `REDIS_URL` unset (every existing dev/test environment) keeps the
in-memory backend exactly as it was; the docker-compose stack sets it to
`redis://redis:6379/0` and gets a sliding window shared across all 4 uvicorn
worker processes via a per-key sorted set (`ZREMRANGEBYSCORE` to evict,
`ZCARD` to count, `ZADD`+`EXPIRE` to record).

**The Redis backend is deliberately not atomic, and that's written down, not
hidden.** A textbook-correct implementation uses a Lua script (`EVAL`) so
the count-then-add is one atomic round trip. This one doesn't: `fakeredis`
(the in-memory Redis emulator used to test this, since no real server is
available here) doesn't support `EVAL`/`EVALSHA` without the optional `lupa`
C-extension — confirmed by actually trying it and reading the resulting
traceback, not assumed. The result is a narrow race (two requests landing in
the same instant right at the limit could both be admitted), judged
acceptable for a best-effort abuse layer — unlike `app/services/quota.py`
(a hard billing boundary, enforced with a real row lock), nothing here needs
to be airtight.

**`X-Forwarded-For` is no longer trusted by default.** `client_ip()`
(`app/api/deps.py`) previously read it unconditionally — fine only because
the docstring already flagged that a directly-exposed instance lets any
client forge its own rate-limit/audit IP by just sending the header itself.
A new `TRUST_PROXY_HEADERS` setting (default `false`) gates it; the
docker-compose backend service sets it `true`, since nginx is what actually
overwrites the header there.

**The SSE no-buffering header (Step 6) finally has something to be
load-bearing against.** `nginx/nginx.conf` sets `proxy_buffering off` on the
whole `/api/` prefix (not just the one streaming route — simpler than a
second location block, harmless for ordinary JSON responses) — the
reverse-proxy config the `X-Accel-Buffering: no` response header was always
written for.

**One nginx origin means the dashboard and backend become same-origin in
production, but CORS is still configured defensively.** Fronting both
through nginx on one public origin (`PUBLIC_ORIGIN`) means the browser's
calls from the dashboard to `/api/...` are no longer cross-origin at all —
but `DASHBOARD_CORS_ORIGINS` is still set to that same origin in
docker-compose, in case anything ever reaches the backend container
directly.

**`NEXT_PUBLIC_*` is baked in at image build time, not read at container
start — a real Next.js gotcha, checked against the actual framework
behavior rather than assumed.** `dashboard/Dockerfile` takes
`NEXT_PUBLIC_API_BASE_URL` as a build `ARG`, not a runtime environment
variable; docker-compose passes it via `build.args`, pointed at
`PUBLIC_ORIGIN` (browser-reachable through nginx) — never the
Docker-internal `http://backend:8000`, which no browser can resolve.
`next.config.ts` also gained `output: "standalone"`, confirmed against the
bundled Next.js 16 docs (this project's Next version is new enough that its
own `AGENTS.md` warns training-data assumptions may not hold) — verified
`.next/standalone/server.js` actually gets produced by a real `npm run
build`, not just assumed from the docs.

**Testing.** Backend: 11 new tests — `test_rate_limit_redis.py` (admits up
to the limit then rejects, independent keys, window eviction via a
module-swapped fake clock, `retry_after` bounds, confirms the in-memory path
is untouched when `REDIS_URL` is unset) against `fakeredis`, and
`test_deps.py` (`X-Forwarded-For` trusted vs. ignored, truncation, the
no-client fallback). Full suite now 231 tests. Dashboard: unchanged by this
step (no dashboard *code* changed — only its Dockerfile/config). Live: the
containerized-stack run described above, exercising the real Redis backend
`test_rate_limit_redis.py` can only fake.

**What's out of scope, same as confirmed upfront.** No WAF/CAPTCHA/anomaly
detection (the abuse-defense territory an earlier README note flagged as
"Step 9/10"), no cloud-provider-specific IaC, no TLS certificates —
`nginx/nginx.conf` has a commented placeholder and a note that real certs
(e.g. via certbot) are a deployment-specific follow-up. A CI pipeline was
originally out of scope here too — added afterward, see below.

## CI

`.github/workflows/ci.yml` — three independent jobs (`backend`, `dashboard`,
`widget`) on every push/PR to `main`, each running that project's real test
suite (and, for the two frontend jobs, a real build) with no paid service
required beyond an ordinary GitHub repo.

**Every job was actually run locally before being trusted, using `act`
(installed via winget) against real Docker containers — not just written
and assumed correct.** This caught two real bugs immediately, both fixed
before this was ever pushed anywhere:

- **The backend job needs a real Postgres service**, matching
  `tests/conftest.py`'s hard requirement that the test database name end in
  `_test` and its `migrated_database` fixture running real alembic
  migrations against it (not `metadata.create_all`) — the workflow spins up
  `postgres:18-alpine` as a service container with health checks, and `act`
  confirmed all 229 tests pass against it from a completely blank database.
- **`node-version: "20"` was wrong and would have failed on real GitHub
  runners too.** `jsdom@30` (a real dependency of this project's test setup,
  not something the workflow added) bundles an `undici` whose `CacheStorage`
  calls a webidl API that doesn't exist before Node 22 — every dashboard
  test crashed with `webidl.util.markAsUncloneable is not a function` the
  instant a test file imported `jsdom`, confirmed by actually hitting that
  exact crash under `act` rather than assuming Node 20 (a still-common LTS)
  would be fine. Both frontend jobs now pin Node 22; after that fix, the
  dashboard's 56 tests + `next build` and the widget's 87 tests + typecheck
  + lint + `vite build` (12.06 kB gzip, matching Step 6's figure) all passed
  for real under `act`.

**One `act`-only artifact, not a real bug.** All three jobs show a harmless
`::warning::` from `actions/setup-node`/`actions/setup-python`'s cache-save
step failing with `tar: /mnt/c/Projects/My: Cannot open: No such file or
directory` — caused by this repository's own path containing a space
(`C:\Projects\My project`) combined with how `act` mounts local Windows
paths into its Linux containers. GitHub's actual hosted runners check out
into a clean, space-free path (`/home/runner/work/...`), so this specific
failure mode cannot occur there; it's disclosed here rather than silently
ignored only because it showed up in real terminal output during
verification, not because it affects the real pipeline.

**Deliberately not optimized for install speed.** The backend job's `pip
install` takes several minutes on a cold cache (the same `torch`/
`sentence-transformers` download documented throughout this README) —
`actions/setup-python`'s built-in pip cache keeps repeat runs fast, but no
attempt was made to pin a CPU-only torch wheel to shrink the initial
download, since that's a real dependency-resolution change to
`requirements.txt` this pass didn't set out to make.
