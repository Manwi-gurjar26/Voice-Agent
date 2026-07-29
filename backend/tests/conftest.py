from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
_DOTENV = dotenv_values(BACKEND_DIR / ".env")

_FALLBACK_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/voiceagent"


def _test_database_url() -> str:
    """Derive the test database URL from the configured one.

    Tests truncate tables and roll back transactions, so pointing them at a
    development database would destroy data. The name is forced to end in
    `_test` and asserted below — this must fail loudly, never fall through.
    """
    url = os.environ.get("DATABASE_URL") or _DOTENV.get("DATABASE_URL") or _FALLBACK_URL
    base, _, name = url.rpartition("/")
    if not name.endswith("_test"):
        url = f"{base}/{name}_test"
    return url


# Must be set before app.core.config is imported anywhere; Settings is cached.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = _test_database_url()
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-long-enough-for-hs256-signing")
os.environ.setdefault("DASHBOARD_CORS_ORIGINS", "")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import get_db
from app.main import create_app

assert settings.database_url.rsplit("/", 1)[-1].endswith("_test"), (
    f"refusing to run tests against {settings.database_url.rsplit('/', 1)[-1]!r} — "
    "the database name must end in '_test'"
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Bring the test database to head once per session.

    Runs the real migrations rather than metadata.create_all, so the tests
    exercise the same DDL that production will get. Synchronous by design:
    alembic's env.py calls asyncio.run(), which would explode inside a
    already-running event loop.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_session(migrated_database) -> AsyncIterator[AsyncSession]:
    """A session whose writes are rolled back when the test ends.

    An outer transaction is opened on a dedicated connection and the session
    joins it in savepoint mode, so `commit()` inside application code releases
    a savepoint instead of committing for real. Nothing reaches disk, and the
    tests stay independent without truncating tables between them.

    NullPool matters: pytest-asyncio gives each test its own event loop, and a
    pooled connection created in a previous loop cannot be reused safely.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app(db_session: AsyncSession):
    """App wired to the rolled-back test session."""
    application = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        # Mirrors production get_db exactly — commit on success, roll back on
        # exception. This matters: code that writes and *then* raises (failed
        # login counters, token-family revocation) behaves completely
        # differently under the two policies, and a passthrough override would
        # let those writes appear to persist when in production they vanish.
        #
        # Safe because join_transaction_mode="create_savepoint" turns commit()
        # into a savepoint release; the outer transaction still discards
        # everything when the test ends.
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise
        else:
            await db_session.commit()

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """In-process HTTP client. Runs the real middleware and exception handlers
    without binding a socket."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac
