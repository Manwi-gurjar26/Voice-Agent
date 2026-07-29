"""In-memory sliding-window rate limiter for the public widget API.

Single-process only: state lives in a module-level dict, so it does not
coordinate across workers or instances. Correct for local dev and a single
uvicorn process. Before running more than one worker or instance (Step 10),
replace the store with Redis (a sorted set or INCR+EXPIRE) without changing
call sites — `check()` is the only function callers depend on.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque

# Crude ceiling so a distributed-key attack (spoofing many IPs) can't grow
# this dict without bound. Real capacity planning belongs to the Redis move.
_MAX_TRACKED_KEYS = 50_000

_buckets: dict[str, deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()


class RateLimitResult:
    __slots__ = ("allowed", "retry_after")

    def __init__(self, allowed: bool, retry_after: int = 0) -> None:
        self.allowed = allowed
        self.retry_after = retry_after


async def check(key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
    """Sliding-window check-and-increment. Every non-rejected call counts."""
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


def _reset_for_tests() -> None:
    _buckets.clear()
