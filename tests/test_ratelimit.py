from app.ratelimit import RateLimiter, TokenBucket


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


async def test_bucket_consumes_and_refills():
    clock = Clock()
    b = TokenBucket(rate=1.0, capacity=2.0, clock=clock)
    await b.acquire(1)
    await b.acquire(1)
    assert b._tokens == 0.0
    clock.advance(2.0)
    await b.acquire(1)
    assert b._tokens == 1.0


async def test_limiter_wait_ok():
    lim = RateLimiter(concurrency=2, rpm=60, tpm=10_000)
    async with lim:
        await lim.wait(10)
    # no exception == pass
