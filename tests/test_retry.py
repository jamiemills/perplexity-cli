"""Tests for retry utilities."""

# pytest 9 ships partially annotated stubs for ``approx``; the resulting
# unknown-member diagnostics are suppressed for this module only.
# pyright: reportUnknownMemberType=false

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

    def test_negative_jitter_is_clamped_at_zero(self) -> None:
        """A sufficiently negative random offset never produces a negative delay."""
        with mock.patch("perplexity_cli.utils.retry._rng.uniform", return_value=-10.0):
            delay = get_backoff_delay(0, base_delay=1.0, max_delay=10.0, jitter_factor=0.1)

        assert delay == 0.0
