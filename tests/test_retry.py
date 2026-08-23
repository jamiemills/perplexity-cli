"""Tests for retry utilities."""

from __future__ import annotations

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
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace tenacity's real sleep with a no-op for deterministic tests."""
    monkeypatch.setattr("tenacity.nap.sleep", lambda _seconds: None)


class TestRetryWithBackoff:
    """Test retry_with_backoff decorator construction."""

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

    def test_decorator_reraises_after_max_attempts(self):
        """Decorated function reraises after exhausting attempts."""

        @retry_with_backoff(max_attempts=2, initial_wait=0.01, max_wait=0.02)
        def always_fails():
            raise PerplexityRequestError("permanent")

        with pytest.raises(PerplexityRequestError):
            always_fails()


class TestRetryHttpRequest:
    """Test retry_http_request wrapper function."""

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

    def test_reraises_after_exhaustion(self):
        """Reraise after all attempts are exhausted."""
        with pytest.raises(PerplexityRequestError):
            retry_http_request(
                lambda: (_ for _ in ()).throw(PerplexityRequestError("fail")),
                max_attempts=2,
                initial_wait=0.01,
                max_wait=0.02,
            )


class TestRetryWithBackoffStopContract:
    """The decorator must stop at max_attempts using bounded waiting."""

    def test_stops_after_max_attempts_with_bounded_sleeps(self, monkeypatch):
        """Exactly max_attempts calls happen and only max_attempts-1 sleeps."""

        class _SleepLimitReached(Exception):
            """Sentinel raised when an unexpected extra backoff sleep occurs."""

        sleeps: list[float] = []

        def fake_sleep(seconds):
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

    def test_default_max_attempts_is_three(self, monkeypatch):
        """Bare invocation performs three attempts before reraising."""
        sleeps: list[float] = []
        monkeypatch.setattr("tenacity.nap.time.sleep", sleeps.append)
        attempts: list[int] = []

        def always_fails():
            attempts.append(1)
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails)
        assert len(attempts) == 3

    def test_default_initial_wait_is_one_second(self, monkeypatch):
        """The first exponential backoff wait is exactly the 1.0s multiplier."""
        sleeps: list[float] = []

        def fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr("tenacity.nap.time.sleep", fake_sleep)

        def always_fails():
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails, max_attempts=2)
        assert sleeps and sleeps[0] == pytest.approx(1.0)

    def test_default_max_wait_caps_long_backoffs(self, monkeypatch):
        """Waits are capped at the documented 10-second maximum."""
        sleeps: list[float] = []
        monkeypatch.setattr("tenacity.nap.time.sleep", sleeps.append)

        def always_fails():
            raise PerplexityRequestError("persistent")

        with pytest.raises(PerplexityRequestError):
            retry_http_request(always_fails, max_attempts=7, initial_wait=1.0)
        assert len(sleeps) == 6
        assert max(sleeps) == pytest.approx(10.0)


class TestSleepWithBackoffDefaults:
    """sleep_with_backoff defaults produce the documented delay window."""

    def test_default_base_delay_is_one_second(self, monkeypatch):
        """Attempt zero sleeps roughly the 1.0 second base delay."""
        delays: list[float] = []
        monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
        sleep_with_backoff(0)
        assert 0.5 <= delays[0] <= 1.5

    def test_default_jitter_window_is_tenth_of_delay(self, monkeypatch):
        """Without an explicit jitter factor the jitter window is 10%."""
        recorded = {}

        def fake_uniform(low, high):
            recorded["low"] = low
            return 0.0

        monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", fake_uniform)
        get_backoff_delay(0, base_delay=1.0, max_delay=60.0)
        assert recorded["low"] == pytest.approx(-0.1)


class TestGetBackoffDelayDefaults:
    """get_backoff_delay default arguments are pinned by behaviour."""

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
