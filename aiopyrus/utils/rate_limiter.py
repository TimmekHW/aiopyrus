from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("aiopyrus.rate_limiter")


class _Bucket:
    """Single token-bucket window.

    Starts full (burst allowed).  Refills at a constant rate.
    When empty, callers block until a token is available.
    """

    def __init__(self, max_requests: int, period: float) -> None:
        self._rate = max_requests / period  # tokens per second
        self._capacity = float(max_requests)
        self._tokens = float(max_requests)  # start full
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # How long until we have 1 token
                wait = (1.0 - self._tokens) / self._rate

            await asyncio.sleep(wait)


class RateLimiter:
    """Composite rate limiter — all configured windows must have capacity.

    All limits apply simultaneously; the most restrictive one wins at any moment.
    Requests are never rejected — they block until a slot is available.

    Parameters
    ----------
    requests_per_second:
        Hard cap per second.  ``None`` = no per-second limit.
    requests_per_minute:
        Hard cap per minute.  ``None`` = no per-minute limit.
    requests_per_10min:
        Baseline cap per 10 minutes.  Default ``5000``.

    Examples
    --------
    Default (5 000 req / 10 min)::

        RateLimiter()

    DИБ-approved strict mode (5 req/s AND 100 req/min AND 5 000 req/10 min)::

        RateLimiter(requests_per_second=5, requests_per_minute=100)
    """

    def __init__(
        self,
        *,
        requests_per_second: int | None = None,
        requests_per_minute: int | None = None,
        requests_per_10min: int = 5000,
    ) -> None:
        self._buckets: list[_Bucket] = []

        if requests_per_second is not None:
            self._buckets.append(_Bucket(requests_per_second, 1.0))
            log.debug("Rate limit: %d req/s", requests_per_second)

        if requests_per_minute is not None:
            self._buckets.append(_Bucket(requests_per_minute, 60.0))
            log.debug("Rate limit: %d req/min", requests_per_minute)

        self._buckets.append(_Bucket(requests_per_10min, 600.0))
        log.debug("Rate limit: %d req/10min (baseline)", requests_per_10min)

    async def acquire(self) -> None:
        """Block until all buckets have capacity, then consume one token each."""
        for bucket in self._buckets:
            await bucket.acquire()
