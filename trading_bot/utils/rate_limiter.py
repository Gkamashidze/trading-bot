"""Token bucket rate limiter — one instance per exchange.

Prevents us from exceeding exchange API rate limits. The limiter is
conservative: it tracks both per-minute and per-second limits.

Exchange limits (from base.yaml):
- Binance: 1200 req/min = 20 req/s (public), 10 orders/s (private)
- Alpaca: 200 req/min

Usage:
    limiter = RateLimiter(requests_per_minute=1200)
    async with limiter.acquire():
        response = await exchange.fetch_ohlcv(...)
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


class RateLimiter:
    """Async token bucket rate limiter.

    Tokens refill at a constant rate. If no tokens are available,
    callers wait (backpressure) rather than dropping requests.

    This is intentionally simple. If we need precise API weight tracking
    (Binance uses request weights, not counts), extend this to
    WeightedRateLimiter with per-endpoint weights.
    """

    def __init__(
        self,
        requests_per_minute: int,
        burst_factor: float = 1.2,
    ) -> None:
        self._rate = requests_per_minute / 60.0  # tokens per second
        self._capacity = requests_per_minute * burst_factor / 60.0
        self._tokens: float = self._capacity
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    @asynccontextmanager
    async def acquire(self, tokens: float = 1.0) -> AsyncGenerator[None, None]:
        """Async context manager: acquire `tokens` before entering the body.

        Blocks until tokens are available (backpressure).
        """
        wait_logged = False
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    break
                wait_time = (tokens - self._tokens) / self._rate

            if not wait_logged:
                log.debug("rate_limiter_waiting", wait_seconds=round(wait_time, 3))
                wait_logged = True

            await asyncio.sleep(wait_time)

        yield


class ExchangeRateLimiterRegistry:
    """Registry of per-exchange rate limiters.

    One registry per process. Each exchange has its own limiter to avoid
    cross-exchange throttling interference.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}

    def register(self, exchange_id: str, requests_per_minute: int) -> RateLimiter:
        limiter = RateLimiter(requests_per_minute)
        self._limiters[exchange_id] = limiter
        return limiter

    def get(self, exchange_id: str) -> RateLimiter | None:
        return self._limiters.get(exchange_id)

    def get_or_create(self, exchange_id: str, requests_per_minute: int = 60) -> RateLimiter:
        if exchange_id not in self._limiters:
            self.register(exchange_id, requests_per_minute)
        return self._limiters[exchange_id]


# Module-level registry singleton
rate_limiter_registry = ExchangeRateLimiterRegistry()
