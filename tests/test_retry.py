"""Tests for retry utilities."""

# pytest 9 ships partially annotated stubs for ``approx``; the resulting
# unknown-member diagnostics are suppressed for this module only.
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import signal
from unittest import mock

import pytest

from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
)
from perplexity_cli.utils.retry import (
    get_backoff_delay,
    get_retry_after_delay,
    is_retryable_error,
    retry_http_request,
    retry_with_backoff,
    sleep_exact,
    sleep_with_backoff,
)


class TestRetryUtilities:
    """Test retry utility functions."""

    def test_is_retryable_error_network_error(self):
        """Test that network errors are retryable."""
        error = PerplexityRequestError("Connection failed")
        assert is_retryable_error(error) is True

    def test_is_retryable_error_5xx(self):
        """Test that 5xx errors are retryable."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=500, request=req)
        error = PerplexityHTTPStatusError("Server error", request=req, response=resp)
        assert is_retryable_error(error) is True

    def test_is_retryable_error_429(self):
        """Test that 429 errors are retryable."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)
        assert is_retryable_error(error) is True

    def test_is_retryable_error_401(self):
        """Test that 401 errors are not retryable."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=401, request=req)
        error = PerplexityHTTPStatusError("Unauthorized", request=req, response=resp)
        assert is_retryable_error(error) is False

    def test_is_retryable_error_403(self):
        """Test that 403 errors are retryable (Cloudflare challenges)."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=403, request=req)
        error = PerplexityHTTPStatusError("Forbidden", request=req, response=resp)
        assert is_retryable_error(error) is True

    def test_is_retryable_error_404(self):
        """Test that 404 errors are not retryable."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=404, request=req)
        error = PerplexityHTTPStatusError("Not found", request=req, response=resp)
        assert is_retryable_error(error) is False

    def test_sleep_with_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sleep with backoff calculation."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        sleep_with_backoff(0, base_delay=0.01, max_delay=1.0)
        assert len(delays) == 1
        assert delays[0] == pytest.approx(0.01, abs=0.002)

    def test_sleep_with_backoff_max_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that backoff respects max delay."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        sleep_with_backoff(10, base_delay=1.0, max_delay=0.1)
        assert len(delays) == 1
        assert delays[0] <= 0.1

    def test_get_backoff_delay_without_jitter(self):
        """Test deterministic backoff delay when jitter is disabled."""
        assert get_backoff_delay(
            2, base_delay=1.0, max_delay=10.0, jitter_factor=0.0
        ) == pytest.approx(4.0)

    def test_get_backoff_delay_with_jitter_is_bounded(self):
        """Test jittered backoff stays within expected bounds."""
        with mock.patch("perplexity_cli.utils.retry._rng.uniform", return_value=0.25):
            delay = get_backoff_delay(1, base_delay=2.0, max_delay=10.0, jitter_factor=0.1)

        assert 0.0 <= delay <= 4.4

    def test_get_retry_after_delay_from_header(self):
        """Test Retry-After is parsed from HTTP headers."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"Retry-After": "3.5"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)

        assert get_retry_after_delay(error) == pytest.approx(3.5)

    def test_get_retry_after_delay_invalid_header_returns_none(self):
        """Test invalid Retry-After values are ignored."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"Retry-After": "later"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)

        assert get_retry_after_delay(error) is None

    def test_get_retry_after_delay_negative_returns_none(self):
        """Test negative Retry-After values fall back to exponential backoff."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"Retry-After": "-3"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)

        assert get_retry_after_delay(error) is None

    def test_get_retry_after_delay_nan_returns_none(self):
        """Test NaN Retry-After values fall back to exponential backoff."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"Retry-After": "nan"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)

        assert get_retry_after_delay(error) is None

    def test_get_retry_after_delay_infinite_returns_none(self):
        """Test infinite Retry-After values fall back to exponential backoff."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"Retry-After": "inf"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)

        assert get_retry_after_delay(error) is None

    def test_get_retry_after_delay_capped_at_max_backoff(self):
        """Test Retry-After values are capped at the maximum backoff delay."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"Retry-After": "120"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)

        assert get_retry_after_delay(error) == pytest.approx(60.0)

    def test_sleep_exact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test sleep_exact records the exact duration."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        sleep_exact(3.5)
        assert delays == [3.5]

    def test_get_retry_after_delay_not_http_status_error(self):
        """Return None for non-PerplexityHTTPStatusError exceptions."""
        assert get_retry_after_delay(ValueError("nope")) is None

    def test_get_retry_after_delay_no_header(self):
        """Return None when Retry-After header is absent."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)
        assert get_retry_after_delay(error) is None


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Replace tenacity's real sleep with a no-op for deterministic tests."""

    def noop_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("tenacity.nap.sleep", noop_sleep)


class _ExcessBackoffSleep(Exception):
    """Sentinel raised when a retry loop sleeps beyond the expected budget."""


def _install_bounded_tenacity_sleep(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], limit: int = 8
) -> None:
    """Record tenacity sleeps and abort runaway retry loops at ``limit`` sleeps.

    Retry-loop mutants that drop the stop condition would otherwise spin or
    sleep forever; the sentinel turns both into an immediate failure.
    """

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) > limit:
            raise _ExcessBackoffSleep("retry loop slept beyond the expected budget")

    monkeypatch.setattr("tenacity.nap.time.sleep", fake_sleep)


class TestRetryWithBackoff:
    """Test retry_with_backoff decorator construction."""

    def test_default_configuration_is_passed_to_tenacity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bare decorator uses every documented default value."""
        calls: dict[str, object] = {}
        stop_strategy = object()
        wait_strategy = object()
        retry_strategy = object()

        def record_stop(attempts: int) -> object:
            calls["stop"] = attempts
            return stop_strategy

        def record_wait(**kwargs: object) -> object:
            calls["wait"] = kwargs
            return wait_strategy

        def record_retry(exception_types: object) -> object:
            calls["retry"] = exception_types
            return retry_strategy

        def record_decorator(**kwargs: object):
            calls["decorator"] = kwargs
            return lambda function: function

        monkeypatch.setattr("perplexity_cli.utils.retry.stop_after_attempt", record_stop)
        monkeypatch.setattr("perplexity_cli.utils.retry.wait_exponential", record_wait)
        monkeypatch.setattr("perplexity_cli.utils.retry.retry_if_exception_type", record_retry)
        monkeypatch.setattr("perplexity_cli.utils.retry.retry", record_decorator)

        retry_with_backoff()

        assert calls["stop"] == 3
        assert calls["wait"] == {"multiplier": 1.0, "max": 10.0, "exp_base": 2.0}
        assert calls["retry"] == (PerplexityRequestError, PerplexityHTTPStatusError)
        assert calls["decorator"] == {
            "stop": stop_strategy,
            "wait": wait_strategy,
            "retry": retry_strategy,
            "reraise": True,
        }

    def test_decorator_retries_on_request_error(self):
        """Decorated function retries and eventually succeeds."""
        call_count = 0

        @retry_with_backoff(max_attempts=3, initial_wait=0.01, max_wait=0.02)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise PerplexityRequestError("transient")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 2

    def test_decorator_reraises_after_max_attempts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decorated function reraises after exhausting attempts."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        @retry_with_backoff(max_attempts=2, initial_wait=0.01, max_wait=0.02)
        def always_fails() -> None:
            raise PerplexityRequestError("permanent")

        with pytest.raises(PerplexityRequestError):
            always_fails()
        assert len(sleeps) == 1


class TestRetryHttpRequest:
    """Test retry_http_request wrapper function."""

    def test_default_configuration_is_forwarded_to_decorator(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper preserves its documented default retry configuration."""
        captured: dict[str, object] = {}

        def fake_retry_with_backoff(**kwargs: object):
            captured.update(kwargs)
            return lambda function: function

        monkeypatch.setattr(
            "perplexity_cli.utils.retry.retry_with_backoff", fake_retry_with_backoff
        )

        assert retry_http_request(lambda: "ok") == "ok"
        assert captured == {"max_attempts": 3, "initial_wait": 1.0, "max_wait": 10.0}

    def test_successful_call(self):
        """Return result from a successful function."""
        assert retry_http_request(lambda: 42, max_attempts=1) == 42

    def test_retries_and_succeeds(self):
        """Retry on transient error then return result."""
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise PerplexityRequestError("transient")
            return "done"

        result = retry_http_request(flaky, max_attempts=3, initial_wait=0.01, max_wait=0.02)
        assert result == "done"
        assert call_count == 2

    def test_reraises_after_exhaustion(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reraise after all attempts are exhausted."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        with pytest.raises(PerplexityRequestError):
            retry_http_request(
                lambda: (_ for _ in ()).throw(PerplexityRequestError("fail")),
                max_attempts=2,
                initial_wait=0.01,
                max_wait=0.02,
            )
        assert len(sleeps) == 1


class TestRetryWithBackoffStopContract:
    """The decorator must stop at max_attempts using bounded waiting."""

    def test_stops_after_max_attempts_with_bounded_sleeps(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exactly max_attempts calls happen and only max_attempts-1 sleeps."""

        class _SleepLimitReached(Exception):
            """Sentinel raised when an unexpected extra backoff sleep occurs."""

        sleeps: list[float] = []

        def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) > 2:
                raise _SleepLimitReached("retrying beyond the configured attempt budget")

        monkeypatch.setattr("tenacity.nap.time.sleep", fake_sleep)
        attempts: list[int] = []

        @retry_with_backoff(max_attempts=3, initial_wait=0.01, max_wait=0.02)
        def always_fails():
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            always_fails()
        assert len(attempts) == 3
        assert len(sleeps) == 2


class TestRetryHttpRequestDefaults:
    """retry_http_request default parameters pin the documented backoff shape."""

    def test_bare_request_uses_three_attempts_and_default_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper preserves all retry defaults when no options are passed."""
        sleeps: list[float] = []
        attempts: list[int] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        def always_fails() -> None:
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails)

        assert len(attempts) == 3
        assert sleeps == pytest.approx([1.0, 2.0])

    def test_default_max_attempts_is_three(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bare invocation performs three attempts before reraising."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)
        attempts: list[int] = []

        def always_fails():
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails)
        assert len(attempts) == 3

    def test_default_initial_wait_is_one_second(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The first exponential backoff wait is exactly the 1.0s multiplier."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        def always_fails():
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails, max_attempts=2)
        assert sleeps and sleeps[0] == pytest.approx(1.0)

    def test_default_max_wait_caps_long_backoffs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Waits are capped at the documented 10-second maximum."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        def always_fails():
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails, max_attempts=7, initial_wait=1.0)
        assert len(sleeps) == 6
        assert max(sleeps) == pytest.approx(10.0)


class TestSleepWithBackoffDefaults:
    """sleep_with_backoff defaults produce the documented delay window."""

    def test_default_arguments_are_used_for_zero_and_capped_attempts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Default base and cap produce one second and sixty seconds."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", lambda _low, _high: 0.0)

        sleep_with_backoff(0)
        sleep_with_backoff(7)

        assert delays == pytest.approx([1.0, 60.0])

    def test_default_base_and_max_delays_are_forwarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The default base is 1s and exponential growth is capped at 60s."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", lambda _low, _high: 0.0)

        sleep_with_backoff(0)
        sleep_with_backoff(7)

        assert delays == pytest.approx([1.0, 60.0])

    def test_default_base_delay_is_one_second(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Attempt zero sleeps roughly the 1.0 second base delay."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        sleep_with_backoff(0)
        assert 0.5 <= delays[0] <= 1.5

    def test_default_jitter_window_is_tenth_of_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without an explicit jitter factor the jitter window is 10%."""
        recorded: dict[str, float] = {}

        def fake_uniform(low: float, high: float) -> float:
            recorded["low"] = low
            return 0.0

        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", fake_uniform)
        get_backoff_delay(0, base_delay=1.0, max_delay=60.0)
        assert recorded["low"] == pytest.approx(-0.1)

    def test_default_max_delay_is_sixty_seconds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Large attempts use the documented sixty-second sleep cap."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", lambda _low, _high: 0.0)

        sleep_with_backoff(7, base_delay=1.0)

        assert delays == pytest.approx([60.0])


class TestGetBackoffDelayDefaults:
    """get_backoff_delay default arguments are pinned by behaviour."""

    def test_default_arguments_define_delay_and_jitter_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Defaults yield a four-second delay with a ten-percent jitter window."""
        bounds: list[tuple[float, float]] = []

        def fake_uniform(low: float, high: float) -> float:
            bounds.append((low, high))
            return high

        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", fake_uniform)

        assert get_backoff_delay(2) == pytest.approx(4.4)
        assert bounds == pytest.approx([(-0.4, 0.4)])

    def test_default_jitter_factor_is_tenth_of_delay(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The default jitter draw spans exactly ten percent of the delay."""
        bounds: list[tuple[float, float]] = []

        def fake_uniform(low: float, high: float) -> float:
            bounds.append((low, high))
            return high

        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", fake_uniform)

        assert get_backoff_delay(2, base_delay=1.0, max_delay=60.0) == pytest.approx(4.4)
        assert bounds == pytest.approx([(-0.4, 0.4)])

    def test_default_max_delay_caps_growth_at_sixty(self):
        """Unbounded exponential growth caps at the 60 second default."""
        assert get_backoff_delay(30, base_delay=1.0, jitter_factor=0.0) == pytest.approx(60.0)

    def test_default_base_delay_is_one_second(self):
        """Attempt zero without a base delay yields one second."""
        assert get_backoff_delay(0, jitter_factor=0.0) == pytest.approx(1.0)


class TestReadRetryAfterHeaderPrecedence:
    """Canonical Retry-After casing takes precedence over lowercase."""

    def test_canonical_header_wins_over_lowercase_duplicate(self):
        """When both casings appear the canonical value is honoured."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(
            status_code=429,
            headers={"Retry-After": "1.5", "retry-after": "9.9"},
            request=req,
        )
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)
        assert get_retry_after_delay(error) == pytest.approx(1.5)

    def test_lowercase_only_header_is_honoured(self):
        """A lowercase-only Retry-After header still supplies the delay."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, headers={"retry-after": "2"}, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)
        assert get_retry_after_delay(error) == pytest.approx(2.0)


def _make_rate_limit_error(retry_after: str) -> PerplexityHTTPStatusError:
    """Build a 429 error carrying the given Retry-After header value."""
    req = SimpleRequest(method="GET", url="http://example.com")
    resp = SimpleResponse(status_code=429, headers={"Retry-After": retry_after}, request=req)
    return PerplexityHTTPStatusError("Rate limit", request=req, response=resp)


class TestRetryAfterSmallValueBoundary:
    """Zero and sub-one Retry-After values remain valid honoured delays."""

    @pytest.mark.parametrize(
        ("header_value", "expected_delay"),
        [
            pytest.param("0", 0.0, id="zero"),
            pytest.param("0.5", 0.5, id="fractional-below-one"),
        ],
    )
    def test_small_retry_after_values_are_honoured(
        self, header_value: str, expected_delay: float
    ) -> None:
        """Retry-After of zero or a fraction below one parses to its exact value."""
        error = _make_rate_limit_error(header_value)

        assert get_retry_after_delay(error) == pytest.approx(expected_delay)


class TestGetBackoffDelayJitterContract:
    """Jitter application follows the documented draw-add-clamp contract."""

    def test_zero_jitter_factor_skips_the_jitter_draw(self) -> None:
        """A zero jitter factor must bypass the random draw entirely."""
        with mock.patch(
            "perplexity_cli.utils.retry._rng.uniform", return_value=5.0
        ) as fake_uniform:
            delay = get_backoff_delay(2, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)

        fake_uniform.assert_not_called()
        assert delay == pytest.approx(4.0)

    def test_jitter_offset_is_added_before_clamping(self) -> None:
        """A drawn jitter offset increases the delay before the max clamp."""
        with mock.patch("perplexity_cli.utils.retry._rng.uniform", return_value=0.25):
            delay = get_backoff_delay(2, base_delay=1.0, max_delay=10.0, jitter_factor=0.1)

        assert delay == pytest.approx(4.25)


class TestRetryWithBackoffWaitShape:
    """Decorator wait parameters must reach tenacity's exponential wait."""

    def test_default_values_are_used_for_attempts_and_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The bare decorator makes three calls with 1s then 2s waits."""
        sleeps: list[float] = []
        attempts: list[int] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        @retry_with_backoff()
        def always_fails() -> None:
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            always_fails()

        assert len(attempts) == 3
        assert sleeps == pytest.approx([1.0, 2.0])

    def test_default_arguments_define_three_attempts_and_exponential_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare decorator uses its documented attempt and wait defaults."""
        sleeps: list[float] = []
        attempts: list[int] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        @retry_with_backoff()
        def always_fails() -> None:
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            always_fails()

        assert len(attempts) == 3
        assert sleeps == pytest.approx([1.0, 2.0])

    def test_initial_wait_is_the_first_wait_multiplier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """initial_wait multiplies the first backoff wait."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        @retry_with_backoff(max_attempts=2, initial_wait=0.5, max_wait=10.0)
        def always_fails() -> None:
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            always_fails()
        assert sleeps == pytest.approx([0.5])

    def test_exponential_base_scales_successive_waits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """exponential_base is the growth factor between consecutive waits."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        @retry_with_backoff(max_attempts=3, initial_wait=1.0, max_wait=10.0, exponential_base=3.0)
        def always_fails() -> None:
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            always_fails()
        assert sleeps == pytest.approx([1.0, 3.0])


class TestRetryWithBackoffRetryPredicate:
    """Only the configured exception types are retried."""

    def test_non_retryable_exception_is_raised_without_retry(self) -> None:
        """A ValueError surfaces on the first attempt without any retry."""
        calls: list[int] = []

        @retry_with_backoff(max_attempts=3, initial_wait=0.01, max_wait=0.02)
        def broken() -> None:
            calls.append(1)
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            broken()
        assert len(calls) == 1


class TestRetryWithBackoffTerminationGuard:
    """The stop condition must bound the retry loop promptly."""

    def test_stop_condition_bounds_attempts_with_watchdog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing stop condition fails fast instead of retrying forever.

        Guards the historically hang-prone decorator mutation with both a
        sleep-budget sentinel and a SIGALRM watchdog copied from the
        termination-guard suite.
        """

        def on_deadline(signum: int, frame: object) -> None:
            raise AssertionError("retry loop exceeded the termination deadline")

        attempts: list[int] = []
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps, limit=5)
        previous = signal.signal(signal.SIGALRM, on_deadline)
        signal.setitimer(signal.ITIMER_REAL, 5.0)

        @retry_with_backoff(max_attempts=3, initial_wait=0.01, max_wait=0.02)
        def always_fails() -> None:
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        try:
            with pytest.raises(PerplexityRequestError):
                always_fails()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

        assert len(attempts) == 3
        assert len(sleeps) == 2


class TestRetryHttpRequestParameterPassthrough:
    """retry_http_request must forward its wait parameters to the decorator."""

    def test_initial_wait_is_forwarded_to_the_wait_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit initial_wait shapes the first tenacity wait."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        def always_fails() -> None:
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails, max_attempts=2, initial_wait=0.5, max_wait=10.0)
        assert sleeps == pytest.approx([0.5])

    def test_max_wait_is_forwarded_to_the_wait_strategy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit max_wait caps the first tenacity wait."""
        sleeps: list[float] = []
        _install_bounded_tenacity_sleep(monkeypatch, sleeps)

        def always_fails() -> None:
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails, max_attempts=2, initial_wait=8.0, max_wait=1.0)
        assert sleeps == pytest.approx([1.0])
