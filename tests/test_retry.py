"""Tests for retry utilities."""

import pytest

import httpx

from perplexity_cli.utils.retry import is_retryable_error, sleep_with_backoff


class TestRetryUtilities:
    """Test retry utility functions."""

    def test_is_retryable_error_network_error(self):
        """Test that network errors are retryable."""
        error = httpx.RequestError("Connection failed")
        assert is_retryable_error(error) is True

    def test_is_retryable_error_5xx(self):
        """Test that 5xx errors are retryable."""
        response = httpx.Response(500, request=httpx.Request("GET", "http://example.com"))
        error = httpx.HTTPStatusError("Server error", request=response.request, response=response)
        assert is_retryable_error(error) is True

    def test_is_retryable_error_429(self):
        """Test that 429 errors are retryable."""
        response = httpx.Response(429, request=httpx.Request("GET", "http://example.com"))
        error = httpx.HTTPStatusError("Rate limit", request=response.request, response=response)
        assert is_retryable_error(error) is True

    def test_is_retryable_error_401(self):
        """Test that 401 errors are not retryable."""
        response = httpx.Response(401, request=httpx.Request("GET", "http://example.com"))
        error = httpx.HTTPStatusError("Unauthorized", request=response.request, response=response)
        assert is_retryable_error(error) is False

    def test_is_retryable_error_403(self):
        """Test that 403 errors are not retryable."""
        response = httpx.Response(403, request=httpx.Request("GET", "http://example.com"))
        error = httpx.HTTPStatusError("Forbidden", request=response.request, response=response)
        assert is_retryable_error(error) is False

    def test_is_retryable_error_404(self):
        """Test that 404 errors are not retryable."""
        response = httpx.Response(404, request=httpx.Request("GET", "http://example.com"))
        error = httpx.HTTPStatusError("Not found", request=response.request, response=response)
        assert is_retryable_error(error) is False

    def test_sleep_with_backoff(self):
        """Test sleep with backoff calculation."""
        import time

        start = time.time()
        sleep_with_backoff(0, base_delay=0.01, max_delay=1.0)
        elapsed = time.time() - start
        # Should sleep approximately 0.01 seconds
        assert 0.005 <= elapsed <= 0.05

    def test_sleep_with_backoff_max_delay(self):
        """Test that backoff respects max delay."""
        import time

        start = time.time()
        sleep_with_backoff(10, base_delay=1.0, max_delay=0.1)  # Max should cap it
        elapsed = time.time() - start
        # Should sleep approximately max_delay (0.1) seconds, not 2^10
        assert elapsed <= 0.2

