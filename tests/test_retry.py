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
        """Test that 403 errors are not retryable."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=403, request=req)
        error = PerplexityHTTPStatusError("Forbidden", request=req, response=resp)
        assert is_retryable_error(error) is False

    def test_is_retryable_error_404(self):
        """Test that 404 errors are not retryable."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=404, request=req)
        error = PerplexityHTTPStatusError("Not found", request=req, response=resp)
        assert is_retryable_error(error) is False

    def test_sleep_with_backoff(self):
        """Test sleep with backoff calculation."""
        import time

        start = time.time()
        sleep_with_backoff(0, base_delay=0.01, max_delay=1.0)
        elapsed = time.time() - start
        # Should sleep approximately 0.01 seconds
        assert 0.005 <= elapsed <= 0.1

    def test_sleep_with_backoff_max_delay(self):
        """Test that backoff respects max delay."""
        import time

        start = time.time()
        sleep_with_backoff(10, base_delay=1.0, max_delay=0.1)  # Max should cap it
        elapsed = time.time() - start
        # Should sleep approximately max_delay (0.1) seconds, not 2^10
        assert elapsed <= 0.2

    def test_get_backoff_delay_without_jitter(self):
        """Test deterministic backoff delay when jitter is disabled."""
        assert get_backoff_delay(
            2, base_delay=1.0, max_delay=10.0, jitter_factor=0.0
        ) == pytest.approx(4.0)

    def test_get_backoff_delay_with_jitter_is_bounded(self):
        """Test jittered backoff stays within expected bounds."""
        with mock.patch("perplexity_cli.utils.retry.random.uniform", return_value=0.25):
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

    def test_get_retry_after_delay_not_http_status_error(self):
        """Return None for non-PerplexityHTTPStatusError exceptions."""
        assert get_retry_after_delay(ValueError("nope")) is None

    def test_get_retry_after_delay_no_header(self):
        """Return None when Retry-After header is absent."""
        req = SimpleRequest(method="GET", url="http://example.com")
        resp = SimpleResponse(status_code=429, request=req)
        error = PerplexityHTTPStatusError("Rate limit", request=req, response=resp)
        assert get_retry_after_delay(error) is None


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
