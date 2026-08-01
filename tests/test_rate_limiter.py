"""Tests for the RateLimiter token bucket implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from perplexity_cli.utils.rate_limiter import RateLimiter

if TYPE_CHECKING:
    pass


class _FakeClock:
    """Deterministic replacement for ``time.monotonic`` and ``asyncio.sleep``."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class _SchedulerClock:
    """Deterministic clock whose ``sleep`` suspends until the clock advances.

    Unlike ``_FakeClock``, ``sleep`` yields control back to the event loop so
    genuinely concurrent waiters can be observed, and only returns once the
    virtual clock has been advanced past the requested wake time. It also
    tracks how many waiters are sleeping simultaneously.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self._real_sleep = asyncio.sleep
        self._sleepers: dict[asyncio.Future[None], float] = {}
        self.active_sleeps = 0
        self.max_active_sleeps = 0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        """Register a sleeper that returns once the clock is advanced."""
        if seconds <= 0:
            return
        self.active_sleeps += 1
        self.max_active_sleeps = max(self.max_active_sleeps, self.active_sleeps)
        wake_time = self.now + seconds
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._sleepers[future] = wake_time
        try:
            await future
        finally:
            self._sleepers.pop(future, None)
            self.active_sleeps -= 1

    async def advance(self, seconds: float) -> None:
        """Advance the virtual clock and wake any sleepers whose time has come."""
        self.now += seconds
        for _ in range(100):
            await self._real_sleep(0)
            await self._real_sleep(0)
            due = [future for future, wake in self._sleepers.items() if wake <= self.now]
            if not due:
                break
            for future in due:
                future.set_result(None)
            await self._real_sleep(0)

    async def yield_control(self) -> None:
        """Yield to the event loop so pending tasks can start."""
        for _ in range(3):
            await self._real_sleep(0)


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    """Patch the rate-limiter module to use a controllable fake clock."""
    clock = _FakeClock()
    monkeypatch.setattr("perplexity_cli.utils.rate_limiter.time.monotonic", clock.monotonic)
    monkeypatch.setattr("perplexity_cli.utils.rate_limiter.asyncio.sleep", clock.sleep)
    return clock


@pytest.fixture
def scheduler_clock(monkeypatch: pytest.MonkeyPatch) -> _SchedulerClock:
    """Patch the rate-limiter module to use a scheduler-driven clock."""
    clock = _SchedulerClock()
    monkeypatch.setattr("perplexity_cli.utils.rate_limiter.time.monotonic", clock.monotonic)
    monkeypatch.setattr("perplexity_cli.utils.rate_limiter.asyncio.sleep", clock.sleep)
    return clock


class TestRateLimiterInitialisation:
    """Test RateLimiter constructor and parameter validation."""

    def test_valid_initialisation(self):
        """Test creation with valid parameters."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=30.0)
        assert limiter.requests_per_period == 10
        assert limiter.period_seconds == pytest.approx(30.0)
        assert limiter._state.tokens == pytest.approx(10.0)
        assert limiter.total_requests == 0
        assert limiter.total_wait_time == pytest.approx(0.0)

    def test_single_request_per_period(self):
        """Test creation with minimum valid requests_per_period."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=1.0)
        assert limiter.requests_per_period == 1
        assert limiter._state.tokens == pytest.approx(1.0)

    def test_large_capacity(self):
        """Test creation with a large number of requests per period."""
        limiter = RateLimiter(requests_per_period=10000, period_seconds=3600.0)
        assert limiter.requests_per_period == 10000
        assert limiter._state.tokens == pytest.approx(10000.0)

    def test_fractional_period_seconds(self):
        """Test creation with fractional period_seconds."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=0.5)
        assert limiter.period_seconds == pytest.approx(0.5)

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

    def test_initial_last_refill_time_is_set(self, fake_clock: _FakeClock) -> None:
        """Test that last_refill_time is initialised to the current monotonic time."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=60.0)
        assert limiter._state.last_refill_time == fake_clock.now


class TestRateLimiterAcquire:
    """Test the acquire() method and token bucket behaviour."""

    @pytest.mark.asyncio
    async def test_acquire_returns_zero_when_tokens_available(self):
        """Test that acquire() returns 0 wait time when tokens are available."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=60.0)
        wait_time = await limiter.acquire()
        assert wait_time == pytest.approx(0.0)
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
    async def test_acquire_waits_when_bucket_empty(self, fake_clock: _FakeClock) -> None:
        """Test that acquire() waits when no tokens are available."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=0.1)

        wait1 = await limiter.acquire()
        assert wait1 == pytest.approx(0.0)

        wait2 = await limiter.acquire()

        assert wait2 > 0.0

    @pytest.mark.asyncio
    async def test_acquire_updates_statistics(self, fake_clock: _FakeClock) -> None:
        """Test that acquire() correctly updates total_requests and total_wait_time."""
        limiter = RateLimiter(requests_per_period=2, period_seconds=0.1)

        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()

        assert limiter.total_requests == 3
        assert limiter.total_wait_time > 0.0

    @pytest.mark.asyncio
    async def test_tokens_do_not_exceed_capacity(self, fake_clock: _FakeClock) -> None:
        """Test that tokens never accumulate beyond the configured capacity."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=0.05)

        await limiter.acquire()

        fake_clock.advance(0.15)

        await limiter.acquire()

        assert limiter._state.tokens <= 5.0

    @pytest.mark.asyncio
    async def test_token_refill_over_time(self, fake_clock: _FakeClock) -> None:
        """Test that tokens are refilled based on elapsed time."""
        limiter = RateLimiter(requests_per_period=10, period_seconds=0.1)

        for _ in range(10):
            await limiter.acquire()

        fake_clock.advance(0.05)

        wait_time = await limiter.acquire()

        assert wait_time == pytest.approx(0.0)


class TestRateLimiterGetStats:
    """Test the get_stats() method."""

    def test_get_stats_initial_state(self):
        """Test get_stats() returns correct initial values."""
        limiter = RateLimiter(requests_per_period=20, period_seconds=60.0)
        stats = limiter.get_stats()

        assert stats["requests_per_period"] == 20
        assert stats["period_seconds"] == pytest.approx(60.0)
        assert stats["total_requests"] == 0
        assert stats["total_wait_time"] == pytest.approx(0.0)
        assert stats["average_wait_per_request"] == pytest.approx(0.0)
        assert stats["current_tokens"] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_get_stats_after_requests(self):
        """Test get_stats() after some requests have been made."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=60.0)

        await limiter.acquire()
        await limiter.acquire()

        stats = limiter.get_stats()

        assert stats["total_requests"] == 2
        assert stats["requests_per_period"] == 5
        assert stats["period_seconds"] == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_get_stats_average_wait_calculation(self, fake_clock: _FakeClock) -> None:
        """Test that average_wait_per_request is calculated correctly."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=0.05)

        await limiter.acquire()
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


class TestRateLimiterConcurrency:
    """Concurrency-safety tests for the lock-protected acquire()."""

    async def _run_burst(
        self,
        limiter: RateLimiter,
        clock: _SchedulerClock,
        total: int,
    ) -> list[tuple[float, float]]:
        """Run ``total`` barrier-released concurrent acquisitions.

        Returns a list of ``(wait_time, release_time)`` tuples.
        """
        barrier = asyncio.Barrier(total)

        async def worker() -> tuple[float, float]:
            await barrier.wait()
            wait = await limiter.acquire()
            return wait, clock.monotonic()

        gather_task = asyncio.gather(*(worker() for _ in range(total)))
        while not gather_task.done():
            await clock.advance(2.0)
        return await gather_task

    @pytest.mark.asyncio
    async def test_simultaneous_burst_never_exceeds_capacity(
        self, scheduler_clock: _SchedulerClock
    ) -> None:
        """A simultaneous burst admits at most bucket capacity immediately."""
        limiter = RateLimiter(requests_per_period=3, period_seconds=3.0)
        total = 8

        results = await self._run_burst(limiter, scheduler_clock, total)
        waits = [wait for wait, _ in results]

        assert sum(1 for wait in waits if wait == 0.0) == 3
        deferred = [wait for wait in waits if wait > 0.0]
        assert len(deferred) == total - 3
        assert all(wait == pytest.approx(1.0) for wait in deferred)
        assert limiter.total_requests == total
        assert sum(waits) == pytest.approx(limiter.total_wait_time)
        assert limiter._state.tokens <= 3.0

    @pytest.mark.asyncio
    async def test_concurrent_waiters_spaced_by_refill_interval(
        self, scheduler_clock: _SchedulerClock
    ) -> None:
        """Concurrent waiters are serialised and never released together."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=1.0)
        total = 4

        results = await self._run_burst(limiter, scheduler_clock, total)
        waits = [wait for wait, _ in results]
        releases = [released_at for _, released_at in results]

        assert sum(1 for wait in waits if wait == 0.0) == 1
        deferred = [wait for wait in waits if wait > 0.0]
        assert len(deferred) == total - 1
        assert all(wait == pytest.approx(1.0) for wait in deferred)
        assert scheduler_clock.max_active_sleeps == 1
        assert len(set(releases)) == total
        assert limiter.total_requests == total

    @pytest.mark.asyncio
    async def test_cancelled_waiter_consumes_no_token(
        self, scheduler_clock: _SchedulerClock
    ) -> None:
        """Cancelling a waiter leaves tokens and statistics consistent."""
        limiter = RateLimiter(requests_per_period=1, period_seconds=1.0)
        assert await limiter.acquire() == pytest.approx(0.0)
        assert limiter.total_requests == 1
        assert limiter._state.tokens == pytest.approx(0.0)

        task = asyncio.create_task(limiter.acquire())
        await scheduler_clock.yield_control()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert limiter.total_requests == 1
        assert limiter._state.tokens == pytest.approx(0.0)
        assert limiter._state.last_refill_time == pytest.approx(1000.0)

        await scheduler_clock.advance(1.5)
        wait = await limiter.acquire()
        assert wait == pytest.approx(0.0)
        assert limiter.total_requests == 2

    @pytest.mark.asyncio
    async def test_backwards_clock_does_not_remove_tokens(self, fake_clock: _FakeClock) -> None:
        """A backwards-moving clock is clamped so tokens are never removed."""
        limiter = RateLimiter(requests_per_period=5, period_seconds=0.05)

        for _ in range(3):
            await limiter.acquire()
        assert limiter._state.tokens == pytest.approx(2.0)

        fake_clock.advance(-0.2)
        wait = await limiter.acquire()
        assert wait == pytest.approx(0.0)
        assert limiter._state.tokens == pytest.approx(1.0)

        fake_clock.advance(0.15)
        await limiter.acquire()
        assert limiter._state.tokens == pytest.approx(4.0)
        assert limiter._state.tokens <= 5.0

    @pytest.mark.asyncio
    async def test_totals_equal_successful_acquisitions(
        self, scheduler_clock: _SchedulerClock
    ) -> None:
        """Statistics only count acquisitions that actually succeeded."""
        limiter = RateLimiter(requests_per_period=2, period_seconds=2.0)
        total = 5

        results = await self._run_burst(limiter, scheduler_clock, total)
        waits = [wait for wait, _ in results]

        assert len(waits) == total
        assert limiter.total_requests == total
        assert sum(waits) == pytest.approx(limiter.total_wait_time)
        assert sum(1 for wait in waits if wait == 0.0) == 2
        assert limiter._state.tokens <= 2.0
