"""Rate limiting: token buckets (rpm/tpm) + concurrency semaphore.

Follows the provider's free-tier rules — conservative caps, no bursts.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable


class TokenBucket:
    """Leaky-bucket-style rate limiter using a monotonic clock."""

    def __init__(self, rate: float, capacity: float, clock: Callable[[], float] = time.monotonic):
        self.rate = rate  # tokens per second
        self.capacity = capacity
        self._clock = clock
        self._tokens = float(capacity)
        self._ts = clock()
        self._lock = asyncio.Lock()

    async def acquire(self, n: float = 1.0) -> None:
        n = max(0.0, n)
        while True:
            async with self._lock:
                now = self._clock()
                self._tokens = min(self.capacity, self._tokens + (now - self._ts) * self.rate)
                self._ts = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                wait = (n - self._tokens) / self.rate
            await asyncio.sleep(wait)


class RateLimiter:
    """Combines a concurrency gate with rpm and tpm token buckets."""

    def __init__(self, concurrency: int, rpm: int, tpm: int):
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._rpm = TokenBucket(rpm / 60.0, float(rpm))
        self._tpm = TokenBucket(tpm / 60.0, float(tpm))

    async def __aenter__(self) -> "RateLimiter":
        await self._sem.acquire()
        return self

    async def __aexit__(self, *exc) -> None:
        self._sem.release()

    async def wait(self, est_tokens: int = 0) -> None:
        await self._rpm.acquire(1.0)
        if est_tokens > 0:
            await self._tpm.acquire(float(est_tokens))
