"""Tests for rate_limit.py's Redis backend, driven against fakeredis (an
in-memory Redis emulator) — no real Redis server needed or available in
this environment. See app/services/billing.py's tests for the analogous
provider-client monkeypatch pattern used for Dodo Payments."""

from __future__ import annotations

import fakeredis.aioredis as fakeredis
import pytest

from app.core.config import settings
from app.services import rate_limit


class _FakeClock:
    """Replaces the `time` name inside rate_limit.py's module namespace, so
    _check_redis's time.time() calls are under test control without
    affecting any other module's use of the real time module."""

    def __init__(self, start: float) -> None:
        self._now = start

    def time(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture(autouse=True)
def _redis_backend(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "redis://fake/0")
    fake_client = fakeredis.FakeRedis()
    monkeypatch.setattr(rate_limit, "get_redis_client", lambda: fake_client)
    yield fake_client
    rate_limit._reset_for_tests()


async def test_admits_up_to_the_limit_then_rejects(_redis_backend):
    for _ in range(3):
        result = await rate_limit.check("agent:1", limit=3, window_seconds=60)
        assert result.allowed is True

    result = await rate_limit.check("agent:1", limit=3, window_seconds=60)
    assert result.allowed is False
    assert result.retry_after > 0


async def test_separate_keys_are_independent(_redis_backend):
    for _ in range(2):
        assert (await rate_limit.check("agent:a", limit=2, window_seconds=60)).allowed is True

    # agent:a is now at its limit, but a different key starts fresh.
    assert (await rate_limit.check("agent:a", limit=2, window_seconds=60)).allowed is False
    assert (await rate_limit.check("agent:b", limit=2, window_seconds=60)).allowed is True


async def test_window_eviction_lets_requests_through_again(monkeypatch, _redis_backend):
    clock = _FakeClock(1_000.0)
    monkeypatch.setattr(rate_limit, "time", clock)

    assert (await rate_limit.check("agent:1", limit=1, window_seconds=10)).allowed is True
    assert (await rate_limit.check("agent:1", limit=1, window_seconds=10)).allowed is False

    clock.advance(11)  # past the 10s window

    assert (await rate_limit.check("agent:1", limit=1, window_seconds=10)).allowed is True


async def test_retry_after_is_bounded_by_the_window(monkeypatch, _redis_backend):
    clock = _FakeClock(1_000.0)
    monkeypatch.setattr(rate_limit, "time", clock)

    await rate_limit.check("agent:1", limit=1, window_seconds=30)
    result = await rate_limit.check("agent:1", limit=1, window_seconds=30)

    assert result.allowed is False
    assert 0 < result.retry_after <= 31


async def test_uses_the_redis_backend_only_when_redis_url_is_set(monkeypatch, _redis_backend):
    monkeypatch.setattr(settings, "redis_url", None)
    calls: list[str] = []

    async def _fake_check_redis(*args, **kwargs):
        calls.append("redis")
        return rate_limit.RateLimitResult(allowed=True)

    monkeypatch.setattr(rate_limit, "_check_redis", _fake_check_redis)

    await rate_limit.check("agent:1", limit=5, window_seconds=60)

    assert calls == []  # in-memory path taken, Redis never touched
