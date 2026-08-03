"""Sliding-window rate limiter for the public widget API.

Two backends, selected by settings.redis_url — every caller uses the same
check()/_reset_for_tests() regardless of which is active (app/api/public_deps.py
never changes):

- In-memory (default, settings.redis_url unset): state lives in a
  module-level dict. Correct for local dev and tests, and for a single
  uvicorn process — it does not coordinate across workers or instances.
- Redis (settings.redis_url set): a sorted set per key, shared by every
  worker/instance — what running more than one process needs. See
  _check_redis's docstring for the one deliberate correctness tradeoff.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque

import redis.asyncio as redis

from app.core.config import settings

# Crude ceiling so a distributed-key attack (spoofing many IPs) can't grow
# the in-memory dict without bound. Redis has no equivalent need — its keys
# expire on their own via EXPIRE.
_MAX_TRACKED_KEYS = 50_000
_REDIS_KEY_PREFIX = "ratelimit:"

_buckets: dict[str, deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()

_redis_client: redis.Redis | None = None


class RateLimitResult:
    __slots__ = ("allowed", "retry_after")

    def __init__(self, allowed: bool, retry_after: int = 0) -> None:
        self.allowed = allowed
        self.retry_after = retry_after


def get_redis_client() -> redis.Redis:
    """Lazily-constructed client — the seam tests monkeypatch to substitute
    a fakeredis instance instead of a real server, mirroring
    llm.get_gemini_client / voice.get_whisper_model."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url)
    return _redis_client


async def check(key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
    """Sliding-window check-and-increment. Every non-rejected call counts."""
    if settings.redis_url:
        return await _check_redis(key, limit=limit, window_seconds=window_seconds)
    return await _check_in_memory(key, limit=limit, window_seconds=window_seconds)


async def _check_in_memory(key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
    now = time.monotonic()
    cutoff = now - window_seconds

    async with _lock:
        if key not in _buckets and len(_buckets) >= _MAX_TRACKED_KEYS:
            # Degrade to "reject unseen keys" rather than let memory grow
            # forever. Keys already being tracked keep working normally.
            return RateLimitResult(allowed=False, retry_after=window_seconds)

        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
            return RateLimitResult(allowed=False, retry_after=retry_after)

        bucket.append(now)
        return RateLimitResult(allowed=True)


async def _check_redis(key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
    """Sliding-window check via a per-key sorted set (member -> its own
    request timestamp as score).

    Not atomic across its two round trips (count, then conditionally add) —
    two requests landing in the same instant right at the limit could both
    be admitted. Acceptable for a best-effort abuse-mitigation layer; unlike
    quota (app/services/quota.py, a hard billing boundary enforced with a
    row lock), nothing here needs to be airtight. A Lua script (EVAL) would
    close this race, but fakeredis's async client — used in tests instead of
    a real server — doesn't support EVAL/EVALSHA without the optional `lupa`
    C-extension, so this was deliberately kept scriptless to stay testable
    without adding that dependency.
    """
    client = get_redis_client()
    redis_key = f"{_REDIS_KEY_PREFIX}{key}"
    now = time.time()
    cutoff = now - window_seconds

    await client.zremrangebyscore(redis_key, 0, cutoff)
    count = await client.zcard(redis_key)

    if count >= limit:
        oldest = await client.zrange(redis_key, 0, 0, withscores=True)
        oldest_score = oldest[0][1] if oldest else now
        retry_after = max(1, int(oldest_score + window_seconds - now) + 1)
        return RateLimitResult(allowed=False, retry_after=retry_after)

    # A unique member per request, not just the timestamp: two requests in
    # the same instant would otherwise share a member and ZADD would update
    # one entry's score instead of adding a second, undercounting.
    member = f"{now}:{uuid.uuid4().hex}"
    await client.zadd(redis_key, {member: now})
    await client.expire(redis_key, window_seconds)
    return RateLimitResult(allowed=True)


def _reset_for_tests() -> None:
    _buckets.clear()
    global _redis_client
    _redis_client = None
