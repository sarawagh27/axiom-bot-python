import os
import time
import unittest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from core.rate_limiter import RateLimiter, TokenBucket  # noqa: E402


class TokenBucketTest(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_waits_without_deadlocking(self) -> None:
        bucket = TokenBucket(capacity=1, refill_rate=20.0)

        self.assertTrue(bucket.try_acquire())
        self.assertFalse(bucket.try_acquire())

        started = time.monotonic()
        await bucket.acquire()
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.04)
        self.assertLess(elapsed, 0.25)

    def test_retry_after_reports_wait_time(self) -> None:
        limiter = RateLimiter(capacity=1, refill_rate=2.0)

        self.assertTrue(limiter.try_acquire(guild_id=123, user_id=456))
        self.assertFalse(limiter.try_acquire(guild_id=123, user_id=456))

        retry_after = limiter.retry_after(guild_id=123, user_id=456)

        self.assertGreater(retry_after, 0.0)
        self.assertLessEqual(retry_after, 0.5)


if __name__ == "__main__":
    unittest.main()
