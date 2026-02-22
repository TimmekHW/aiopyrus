"""Tests for RateLimiter (token bucket)."""

from __future__ import annotations

import time

from aiopyrus.utils.rate_limiter import RateLimiter, _Bucket


class TestBucket:
    async def test_burst_capacity(self):
        """Bucket starts full — first N requests go through instantly."""
        b = _Bucket(max_requests=5, period=1.0)
        start = time.monotonic()
        for _ in range(5):
            await b.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # all 5 should be instant

    async def test_blocks_when_empty(self):
        """After burst, acquiring blocks until tokens refill."""
        b = _Bucket(max_requests=2, period=1.0)
        await b.acquire()
        await b.acquire()
        # Bucket is now empty, 3rd acquire should block
        start = time.monotonic()
        await b.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3  # should wait ~0.5s for 1 token


class TestRateLimiter:
    async def test_default_limiter(self):
        """Default limiter (5000/10min) allows burst."""
        rl = RateLimiter()
        start = time.monotonic()
        for _ in range(10):
            await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    async def test_strict_per_second(self):
        """Per-second limit restricts throughput."""
        rl = RateLimiter(requests_per_second=2, requests_per_10min=5000)
        # First 2 instant (burst), 3rd must wait
        start = time.monotonic()
        await rl.acquire()
        await rl.acquire()
        await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3

    async def test_multiple_buckets(self):
        """All configured limits are enforced simultaneously."""
        rl = RateLimiter(requests_per_second=10, requests_per_minute=3, requests_per_10min=5000)
        # per-minute=3 is most restrictive for burst
        start = time.monotonic()
        for _ in range(3):
            await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1  # burst of 3 OK

        # 4th should block (per-minute bucket exhausted)
        start = time.monotonic()
        await rl.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.5  # needs to wait for minute bucket refill
