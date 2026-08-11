"""Application settings, loaded once from the environment."""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General ---
    app_name: str = "Voice Agent Platform"
    app_env: AppEnv = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/voiceagent"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- Security ---
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    jwt_algorithm: str = "HS256"

    # --- CORS (dashboard API only) ---
    # NoDecode is load-bearing: without it, pydantic-settings tries to
    # json.loads() this value inside the env/dotenv source *before* any
    # validator runs, so a plain `A,B` line in .env raises SettingsError and
    # the app cannot start. NoDecode hands the raw string to _split_origins.
    dashboard_cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Public URLs (used to build the customer's embed snippet) ---
    # 127.0.0.1, not localhost: confirmed live that on a machine with
    # WSL2/Docker Desktop installed, "localhost" can resolve to ::1 first
    # and get silently forwarded into WSL instead of reaching this backend
    # (which only binds 127.0.0.1) — the embedded widget's config fetch
    # failed with a CORS/network error and never rendered at all, with no
    # error visible on the customer's page besides a browser console log.
    public_base_url: str = "http://127.0.0.1:8000"
    widget_cdn_url: str = "http://127.0.0.1:5173/widget.js"

    # --- Auth policy ---
    min_password_length: int = 12
    max_failed_logins: int = 10
    login_lockout_minutes: int = 15

    # --- Public widget API ---
    widget_session_expire_minutes: int = 60
    public_rate_limit_window_seconds: int = 60

    # --- LLM ---
    # Google Gemini, not Claude — Claude has no perpetual free tier and this
    # project cannot take on any paid API cost. Gemini's free tier (Google AI
    # Studio) needs only a Google account, no card.
    #
    # "gemini-flash-latest", not a pinned version: confirmed live (with a
    # real free-tier key) that Google had already stopped issuing
    # gemini-2.5-flash to new API keys/projects ("This model ... is no
    # longer available to new users", a real 404 from the live API, not a
    # guess) — the exact deprecation the README warns pinned model ids are
    # exposed to. The "-latest" alias is Google's own mechanism for this:
    # it always resolves to their current recommended flash model, so this
    # setting doesn't go stale the next time they retire one. Overridable
    # per-agent via Agent.model regardless.
    # Typed chat runs on Groq. Gemini's free tier allows only 20
    # generate-content requests per day per model (confirmed from a live 429:
    # quotaId GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue
    # 20), which a single busy afternoon on one customer's site exhausts —
    # after that the widget stops answering entirely. Groq's free allowance
    # for this model is 1,000 requests/day. Gemini remains as a fallback when
    # a key is configured; see chat.py's _stream_gemini_reply.
    gemini_api_key: str | None = None
    gemini_fallback_model: str = "gemini-flash-latest"
    # 70b rather than the 8b model voice uses: a typed answer is read, not
    # heard, so quality matters more than the last few hundred milliseconds.
    default_model: str = "llama-3.3-70b-versatile"

    # --- RAG (Step 5) ---
    # Local model — no API key needed. Swappable, but the embedding dimension
    # is baked into every stored vector: changing models means re-embedding
    # every existing chunk, not just updating this setting.
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size_chars: int = 1_000
    chunk_overlap_chars: int = 150
    retrieval_top_k: int = 5
    # 0.3 was too strict for all-MiniLM-L6-v2's cosine-similarity range on
    # short queries against a multi-topic chunk (a real crawled page mixing
    # several facts in one paragraph) — a genuinely relevant query scored
    # ~0.24 and got dropped. Lowered to 0.2 after checking the real gap
    # against unrelated queries against the same chunk (they scored
    # 0.04-0.07, sometimes negative), so this still has a comfortable margin
    # on both sides, not just a number that happened to let one case through.
    retrieval_min_similarity: float = 0.2

    # Ingestion runs synchronously within the request (see README) — these
    # bound worst-case request latency and cost, not just abuse.
    max_pasted_text_chars: int = 200_000
    max_upload_file_bytes: int = 5 * 1024 * 1024
    url_fetch_timeout_seconds: float = 10.0
    max_url_response_bytes: int = 5 * 1024 * 1024

    # --- Website-crawl ingestion (Firecrawl) ---
    # Firecrawl's own crawl job runs asynchronously on their servers — see
    # app/services/firecrawl.py — this backend starts it, then polls until
    # done, still within the one synchronous request (same tradeoff as the
    # rest of ingestion above). max_crawl_pages caps pages per crawl, since
    # Firecrawl bills per page scraped and the free tier is a fixed monthly
    # credit pool shared by every crawl any tenant runs.
    firecrawl_api_key: str | None = None
    max_crawl_pages: int = 20
    crawl_poll_timeout_seconds: float = 180.0
    crawl_poll_interval_seconds: float = 3.0
    # JS-rendered sites (Streamlit, React/Vue SPAs, etc.) return an empty
    # loading shell if scraped immediately — confirmed live against a real
    # Streamlit Community Cloud app, which returned only the host's generic
    # "app is loading" placeholder with no waitFor, and the actual page
    # content once given 15s to hydrate over its WebSocket connection.
    crawl_wait_for_ms: int = 15000

    # --- Voice (Step 7) ---
    # Turn-based pipeline: Groq (STT via whisper-large-v3-turbo, and the
    # reply LLM via llama-3.1-8b-instant — see app/services/chat.py's
    # complete_turn) and Fish Audio (TTS via its s2.1-pro-free model — see
    # app/services/voice.py). voice_enabled is per-agent (see Agent model).
    # groq_api_key is separate from gemini_api_key: Groq is used only for
    # voice, typed chat runs on Groq's chat model (see default_model).
    #
    # voice_default_voice must stay set. Fish Audio's free model picks from
    # its whole multilingual catalogue when no reference_id is given, so the
    # speaker changes between replies: measuring the synthesized pitch across
    # four identical requests gave 131 Hz, 174 Hz, 123 Hz, 113 Hz — male, then
    # female, then male, and occasionally a voice from another language, which
    # is what made replies sound like they switched language mid-conversation.
    # Pinning a reference_id holds one speaker (the same measurement then
    # spans 17 Hz) and keeps every reply in English. Contrary to an earlier
    # note here, the free s2.1-pro-free model does honour reference_id.
    groq_api_key: str | None = None
    fish_audio_api_key: str | None = None
    voice_default_voice: str | None = "933563129e564b19a115bedd57b7406a"
    # Locks both ends of the spoken turn: Whisper is told what language to
    # expect rather than guessing from a short, accented clip, and the reply
    # is asked for in the same language. Auto-detection drifting mid-sentence
    # is what makes an assistant answer in a language the visitor never used.
    voice_language: str = "en"
    voice_language_name: str = "English"
    max_voice_upload_bytes: int = 10 * 1024 * 1024

    # --- Billing (Step 9) ---
    # Dodo Payments, not Stripe — Stripe does not onboard new India-registered
    # accounts, which blocked live verification entirely on a fresh account.
    # Dodo is a merchant-of-record gateway with the same test/live-mode split
    # and free sandbox testing. Product IDs are created in the merchant's own
    # Dodo dashboard and differ per environment — never hardcoded.
    # dashboard_base_url is used to build Checkout return/cancel URLs and the
    # Customer Portal return URL; nothing before this pointed the backend at
    # the dashboard's own origin.
    dodo_api_key: str | None = None
    dodo_webhook_key: str | None = None
    dodo_environment: Literal["test_mode", "live_mode"] = "test_mode"
    dodo_product_id_starter: str | None = None
    dodo_product_id_pro: str | None = None
    dodo_product_id_enterprise: str | None = None
    dashboard_base_url: str = "http://localhost:3000"

    # --- Password reset (Resend) ---
    # No RESEND_API_KEY configured -> app/services/email.py logs the reset
    # link instead of emailing it, so this whole flow is testable locally
    # without a Resend account. email_from defaults to Resend's own
    # no-verification-needed testing sender.
    resend_api_key: str | None = None
    email_from: str = "onboarding@resend.dev"
    password_reset_token_expire_minutes: int = 30

    # --- Deployment (Step 10) ---
    # Unset (default) keeps app/services/rate_limit.py on its in-memory
    # backend — correct for local dev/tests and a single process. Set this
    # once running more than one worker/instance, and the same rate_limit.check()
    # call sites switch to the Redis-backed implementation with no code change.
    redis_url: str | None = None
    # Default-safe: X-Forwarded-For is attacker-controlled unless something
    # in front of this process (nginx, a load balancer) overwrites it before
    # the request arrives. Only flip this on for a deployment that actually
    # sits behind such a proxy — see app/api/deps.py::client_ip.
    trust_proxy_headers: bool = False

    @field_validator("dashboard_cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string as well as a JSON list.

        pydantic-settings parses complex types as JSON by default, which makes a
        plain `A,B` value in .env a hard error. Both forms are normalised here,
        including the JSON one — pydantic only auto-parses JSON for values that
        came from the env source, not for direct constructor arguments.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"malformed JSON list: {exc}") from exc
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must use the asyncpg driver, "
                "e.g. postgresql+asyncpg://user:pass@host:5432/dbname"
            )
        return value

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.app_env == "production":
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if len(self.secret_key) < 32 or self.secret_key.startswith("change-me"):
                raise ValueError("SECRET_KEY must be a strong, explicitly-set value in production")
        return self

    @property
    def sync_database_url(self) -> str:
        """psycopg-style URL for Alembic, which runs migrations synchronously."""
        return self.database_url.replace("+asyncpg", "", 1)

    @property
    def is_local(self) -> bool:
        return self.app_env in ("local", "test")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
