"""Rate limiting utilities for API requests.

Implements a token bucket algorithm to enforce request rate limits.
This prevents overwhelming the API with too many concurrent requests.
"""

import asyncio
import time

from perplexity_cli.utils.rate_limiter_models import RateLimiterState, RateLimiterStats


class RateLimiter:
    """Token bucket-based rate limiter for API requests.

    Allows a specified number of requests within a time period, with
    automatic waiting to spread requests over time.

    Example:
        # Allow 20 requests per 60 seconds
        limiter = RateLimiter(requests_per_period=20, period_seconds=60)

        # Before each request, acquire a token (waits if necessary)
        await limiter.acquire()
        response = await client.get(url)
    """

    def __init__(self, requests_per_period: int, period_seconds: float) -> None:
        """Initialise rate limiter.

        Args:
            requests_per_period: Number of requests allowed in the period.
            period_seconds: Time period in seconds.

        Raises:
            ValueError: If parameters are invalid.
        """
        if requests_per_period <= 0:
            raise ValueError("requests_per_period must be greater than 0")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be greater than 0")

        self.requests_per_period = requests_per_period
        self.period_seconds = period_seconds

        # Token bucket state managed by Pydantic model
        self._state = RateLimiterState(
            tokens=float(requests_per_period),
            last_refill_time=time.monotonic(),
            requests_per_period=requests_per_period,
            period_seconds=period_seconds,
        )

        # Statistics
        self.total_requests = 0
        self.total_wait_time = 0.0

    async def acquire(self) -> float:
        """Acquire a token, waiting if necessary.

        This method implements the token bucket algorithm:
        1. Refill tokens based on time elapsed since last request
        2. If tokens available, consume one and return immediately
        3. If no tokens, calculate wait time and sleep asynchronously
        4. After sleep, consume token and return

        Returns:
            float: The time waited in seconds (0 if no wait was necessary).
        """
        current_time = time.monotonic()
        time_elapsed = current_time - self._state.last_refill_time

        # Refill tokens based on elapsed time
        # Rate of refill: requests_per_period / period_seconds tokens per second
        refill_rate = self.requests_per_period / self.period_seconds
        tokens_earned = time_elapsed * refill_rate

        # Cap tokens at the maximum (don't accumulate beyond capacity)
        self._state.tokens = min(self.requests_per_period, self._state.tokens + tokens_earned)
        self._state.last_refill_time = current_time

        wait_time = 0.0

        # Check if we have tokens available
        if self._state.tokens >= 1.0:
            # Consume one token and proceed immediately
            self._state.tokens -= 1.0
        else:
            # No tokens available, calculate wait time
            # We need 1 token, and we have self._state.tokens
            # Time to earn remaining tokens: (1 - tokens) / refill_rate
            tokens_needed = 1.0 - self._state.tokens
            wait_time = tokens_needed / refill_rate

            # Sleep asynchronously
            if wait_time > 0.0:
                await asyncio.sleep(wait_time)

            # After sleep, reset state and consume one token
            self._state.tokens = 0.0
            self._state.last_refill_time = time.monotonic()

        # Update statistics
        self.total_requests += 1
        self.total_wait_time += wait_time

        return wait_time

    def get_stats(self) -> dict[str, int | float]:
        """Get rate limiter statistics.

        Returns:
            Dictionary with keys:
                - requests_per_period: Configured request limit
                - period_seconds: Configured time period
                - total_requests: Total requests made
                - total_wait_time: Total time spent waiting
                - average_wait_per_request: Average wait time per request
                - current_tokens: Current token bucket fill level
        """
        stats = RateLimiterStats.from_data(
            total_requests=self.total_requests,
            total_wait_time=self.total_wait_time,
        )
        stats_dict = stats.model_dump()

        return {
            "requests_per_period": self.requests_per_period,
            "period_seconds": self.period_seconds,
            "total_requests": stats_dict["total_requests"],
            "total_wait_time": stats_dict["total_wait_time"],
            "average_wait_per_request": stats_dict["average_wait_time"],
            "current_tokens": self._state.tokens,
        }

    def __repr__(self) -> str:
        """Return string representation of rate limiter."""
        return (
            f"RateLimiter("
            f"requests_per_period={self.requests_per_period}, "
            f"period_seconds={self.period_seconds})"
        )
