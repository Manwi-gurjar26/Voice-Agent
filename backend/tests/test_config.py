from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BASE = {
    "secret_key": "a-sufficiently-long-secret-key-for-testing-purposes-only",
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
}


def make_settings(**overrides) -> Settings:
    """Build Settings in isolation from the developer's local .env.

    Without `_env_file=None` these tests read whatever happens to be in
    backend/.env, so results depend on the machine they run on.
    """
    return Settings(_env_file=None, **{**BASE, **overrides})


def test_cors_origins_accept_a_comma_separated_string():
    s = make_settings(dashboard_cors_origins="http://a.com, http://b.com ,")
    assert s.dashboard_cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_accept_a_json_list():
    s = make_settings(dashboard_cors_origins='["http://a.com"]')
    assert s.dashboard_cors_origins == ["http://a.com"]


def test_empty_cors_origins_is_an_empty_list():
    assert make_settings(dashboard_cors_origins="").dashboard_cors_origins == []


# The three tests below exercise the *settings sources*, not just constructor
# kwargs. pydantic-settings JSON-decodes complex fields inside the env and
# dotenv sources before any validator runs, so a CSV value used to raise
# SettingsError at import time and prevent the app from starting at all.
# Constructor-kwarg tests bypass those sources and cannot catch it.


def test_cors_origins_load_as_csv_from_an_environment_variable(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", "http://a.com,http://b.com")
    s = Settings(_env_file=None)
    assert s.dashboard_cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_load_as_json_from_an_environment_variable(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CORS_ORIGINS", '["http://a.com"]')
    s = Settings(_env_file=None)
    assert s.dashboard_cors_origins == ["http://a.com"]


def test_cors_origins_load_as_csv_from_a_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DASHBOARD_CORS_ORIGINS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("DASHBOARD_CORS_ORIGINS=http://a.com,http://b.com\n", encoding="utf-8")
    s = Settings(_env_file=str(env_file))
    assert s.dashboard_cors_origins == ["http://a.com", "http://b.com"]


def test_sync_url_strips_the_async_driver_for_alembic():
    assert make_settings().sync_database_url == "postgresql://u:p@localhost:5432/db"


def test_a_sync_database_url_is_rejected():
    with pytest.raises(ValidationError, match="asyncpg"):
        make_settings(database_url="postgresql://u:p@localhost:5432/db")


def test_production_rejects_debug_mode():
    with pytest.raises(ValidationError, match="DEBUG"):
        make_settings(app_env="production", debug=True)


def test_production_rejects_a_placeholder_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        make_settings(
            app_env="production",
            debug=False,
            secret_key="change-me-this-is-not-secure",
        )


def test_production_accepts_a_strong_explicit_secret_key():
    s = make_settings(app_env="production", debug=False)
    assert s.app_env == "production"
    assert s.is_local is False
