import asyncio
import time
from dataclasses import dataclass


@dataclass
class BucketState:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """Async-safe in-memory token bucket limiter."""

    def __init__(self, rate: float, burst: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if burst <= 0:
            raise ValueError("burst must be > 0")
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, BucketState] = {}
        self._lock = asyncio.Lock()

    def _refill(self, bucket: BucketState, now: float) -> None:
        elapsed = max(0.0, now - bucket.last_refill)
        bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rate)
        bucket.last_refill = now

    async def allow(self, key: str, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = BucketState(tokens=self.burst, last_refill=now)
                self._buckets[key] = bucket

            self._refill(bucket, now)
            if bucket.tokens >= tokens:
                bucket.tokens -= tokens
                return True
            return False
