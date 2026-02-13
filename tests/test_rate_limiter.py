"""Tests for the RateLimiter token bucket implementation."""

import asyncio
import time

import pytest

from perplexity_cli.utils.rate_limiter import RateLimiter


class TestRateLimiterInitialisation:
    """Test RateLimiter constructor and parameter validation."""

    def test_valid_initialisation(self):
        """Test creation with valid parameters."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=30.0)
        assert limiter.requests_per_period == 10
        assert limiter.period_seconds == 30.0
        assert limiter._state.tokens == 10.0
        assert limiter.total_requests == 0
        assert limiter.total_wait_time == 0.0

    def test_single_request_per_period(self):
        """Test creation with minimum valid requests_per_period."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=1.0)
        assert limiter.requests_per_period == 1
        assert limiter._state.tokens == 1.0

    def test_large_capacity(self):
        """Test creation with a large number of requests per period."""
        limiter = RateLimiter(requests_per_period=10000, period_seconds=3600.0)
        assert limiter.requests_per_period == 10000
        assert limiter._state.tokens == 10000.0

    def test_fractional_period_seconds(self):
        """Test creation with fractional period_seconds."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=0.5)
        assert limiter.period_seconds == 0.5

    def test_zero_requests_per_period_raises(self):
        """Test that zero requests_per_period raises ValueError."""
        with pytest.raises(ValueError, match="requests_per_period must be greater than 0"):
            RateLimiter(requests_per_period=0, period_seconds=60.0)

    def test_negative_requests_per_period_raises(self):
        """Test that negative requests_per_period raises ValueError."""
        with pytest.raises(ValueError, match="requests_per_period must be greater than 0"):
            RateLimiter(requests_per_period=-5, period_seconds=60.0)

    def test_zero_period_seconds_raises(self):
        """Test that zero period_seconds raises ValueError."""
        with pytest.raises(ValueError, match="period_seconds must be greater than 0"):
            RateLimiter(requests_per_period=10, period_seconds=0)

    def test_negative_period_seconds_raises(self):
        """Test that negative period_seconds raises ValueError."""
        with pytest.raises(ValueError, match="period_seconds must be greater than 0"):
            RateLimiter(requests_per_period=10, period_seconds=-1.0)

    def test_initial_last_refill_time_is_set(self):
        """Test that last_refill_time is initialised to a recent monotonic time."""
        before = time.monotonic()
        limiter = RateLimiter(requests_per_period=10, period_seconds=60.0)
        after = time.monotonic()
        assert before <= limiter._state.last_refill_time <= after


class TestRateLimiterAcquire:
    """Test the acquire() method and token bucket behaviour."""

    @pytest.mark.asyncio
    async def test_acquire_returns_zero_when_tokens_available(self):
        """Test that acquire() returns 0 wait time when tokens are available."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=60.0)
        wait_time = await limiter.acquire()
        assert wait_time == 0.0
        assert limiter.total_requests == 1

    @pytest.mark.asyncio
    async def test_acquire_consumes_tokens(self):
        """Test that acquire() consumes one token per call."""
        limiter = RateLimiter(requests_per_period=3, period_seconds=60.0)
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()
        assert limiter.total_requests == 3
        # After consuming 3 tokens from a capacity of 3, tokens should be near 0
        # (some refill may have occurred during the calls)
        assert limiter._state.tokens < 1.0

    @pytest.mark.asyncio
    async def test_acquire_waits_when_bucket_empty(self):
        """Test that acquire() waits when no tokens are available."""
        # Use a very short period so the test runs quickly
        limiter = RateLimiter(requests_per_period=1, period_seconds=0.1)

        # First acquire should be immediate
        wait1 = await limiter.acquire()
        assert wait1 == 0.0

        # Second acquire should wait (bucket is empty)
        start = time.monotonic()
        wait2 = await limiter.acquire()
        elapsed = time.monotonic() - start

        assert wait2 > 0.0
        assert elapsed >= 0.05  # Should have waited a meaningful amount

    @pytest.mark.asyncio
    async def test_acquire_updates_statistics(self):
        """Test that acquire() correctly updates total_requests and total_wait_time."""
        limiter = RateLimiter(requests_per_period=2, period_seconds=0.1)

        await limiter.acquire()
        await limiter.acquire()
        # Third call will need to wait
        await limiter.acquire()

        assert limiter.total_requests == 3
        assert limiter.total_wait_time > 0.0

    @pytest.mark.asyncio
    async def test_tokens_do_not_exceed_capacity(self):
        """Test that tokens never accumulate beyond the configured capacity."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=0.05)

        # Consume one token
        await limiter.acquire()

        # Wait long enough for full refill and then some
        await asyncio.sleep(0.15)

        # Trigger refill by acquiring
        await limiter.acquire()

        # Tokens should not exceed capacity (5) minus the one just consumed
        assert limiter._state.tokens <= 5.0

    @pytest.mark.asyncio
    async def test_token_refill_over_time(self):
        """Test that tokens are refilled based on elapsed time."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=0.1)

        # Consume all tokens
        for _ in range(10):
            await limiter.acquire()

        # Wait for some refill
        await asyncio.sleep(0.05)

        # Next acquire should refill tokens based on elapsed time
        wait_time = await limiter.acquire()

        # After 0.05s with 10 req/0.1s = 100 req/s, we should have earned ~5 tokens
        # so we should not need to wait
        assert wait_time == 0.0


class TestRateLimiterGetStats:
    """Test the get_stats() method."""

    def test_get_stats_initial_state(self):
        """Test get_stats() returns correct initial values."""
        limiter = RateLimiter(requests_per_period=20, period_seconds=60.0)
        stats = limiter.get_stats()

        assert stats["requests_per_period"] == 20
        assert stats["period_seconds"] == 60.0
        assert stats["total_requests"] == 0
        assert stats["total_wait_time"] == 0.0
        assert stats["average_wait_per_request"] == 0.0
        assert stats["current_tokens"] == 20.0

    @pytest.mark.asyncio
    async def test_get_stats_after_requests(self):
        """Test get_stats() after some requests have been made."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=60.0)

        await limiter.acquire()
        await limiter.acquire()

        stats = limiter.get_stats()

        assert stats["total_requests"] == 2
        assert stats["requests_per_period"] == 5
        assert stats["period_seconds"] == 60.0

    @pytest.mark.asyncio
    async def test_get_stats_average_wait_calculation(self):
        """Test that average_wait_per_request is calculated correctly."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=0.05)

        # First request: no wait
        await limiter.acquire()
        # Second request: will wait
        await limiter.acquire()

        stats = limiter.get_stats()

        assert stats["total_requests"] == 2
        assert stats["total_wait_time"] > 0.0
        expected_avg = stats["total_wait_time"] / stats["total_requests"]
        assert abs(stats["average_wait_per_request"] - expected_avg) < 1e-9

    def test_get_stats_returns_dict(self):
        """Test that get_stats() returns a dictionary with expected keys."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=30.0)
        stats = limiter.get_stats()

        expected_keys = {
            "requests_per_period",
            "period_seconds",
            "total_requests",
            "total_wait_time",
            "average_wait_per_request",
            "current_tokens",
        }
        assert set(stats.keys()) == expected_keys


class TestRateLimiterRepr:
    """Test the __repr__() method."""

    def test_repr_format(self):
        """Test that __repr__() returns the expected format."""
        limiter = RateLimiter(requests_per_period=20, period_seconds=60.0)
        result = repr(limiter)
        assert result == "RateLimiter(requests_per_period=20, period_seconds=60.0)"

    def test_repr_with_different_values(self):
        """Test __repr__() with different configuration values."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=0.5)
        result = repr(limiter)
        assert result == "RateLimiter(requests_per_period=5, period_seconds=0.5)"

    def test_repr_is_str(self):
        """Test that __repr__() returns a string."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=30.0)
        assert isinstance(repr(limiter), str)
