"""
core/rate_limiter.py — Token bucket rate limiter.
Sits at two layers: command invocation guard + inside the ping loop.
"""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("axiom.rate_limiter")


class TokenBucket:
    """
    Classic token bucket implementation.

    Tokens refill at `refill_rate` tokens/second up to `capacity`.
    `acquire()` consumes one token; if empty, waits until a token is available.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate  # tokens per second
        self._tokens: float = float(capacity)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self, tokens: int = 1) -> None:
        """Block until `tokens` tokens are available, then consume them."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate wait time and sleep outside the lock
                deficit = tokens - self._tokens
                wait = deficit / self._refill_rate
                log.debug("Rate limiter throttling — waiting %.3fs", wait)
            # Unreachable but satisfies linters
            await asyncio.sleep(wait)  # type: ignore[possibly-undefined]

    def try_acquire(self, tokens: int = 1) -> bool:
        """Non-blocking attempt. Returns True if acquired, False if throttled."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens

    @property
    def capacity(self) -> int:
        return self._capacity


class RateLimiter:
    """
    Per-entity rate limiter registry.
    Maintains a separate TokenBucket per (guild_id, user_id) pair
    and a shared global bucket for bot-wide Discord API protection.
    """

    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._buckets: dict[tuple[int, int], TokenBucket] = {}
        # Global bucket protects the bot's overall Discord API quota
        self._global = TokenBucket(capacity=capacity * 5, refill_rate=refill_rate * 3)

    def _get_bucket(self, guild_id: int, user_id: int) -> TokenBucket:
        key = (guild_id, user_id)
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(self._capacity, self._refill_rate)
        return self._buckets[key]

    async def acquire(self, guild_id: int, user_id: int) -> None:
        """Acquire from both per-user and global buckets (waits if needed)."""
        await self._get_bucket(guild_id, user_id).acquire()
        await self._global.acquire()

    def try_acquire(self, guild_id: int, user_id: int) -> bool:
        """Non-blocking check: returns False immediately if throttled."""
        bucket = self._get_bucket(guild_id, user_id)
        if not bucket.try_acquire():
            return False
        if not self._global.try_acquire():
            # Return the per-user token since global failed
            bucket._tokens += 1
            return False
        return True

    def cleanup(self, guild_id: int, user_id: int) -> None:
        """Remove a user's bucket after their session ends."""
        self._buckets.pop((guild_id, user_id), None)


# Module-level singleton
from config import CONFIG  # noqa: E402
rate_limiter = RateLimiter(
    capacity=CONFIG.rate_limit_tokens,
    refill_rate=CONFIG.rate_limit_refill_rate,
)
