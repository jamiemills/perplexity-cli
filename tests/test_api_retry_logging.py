"""Retry-decision and debug-logging behaviour tests for the API client.

These tests pin ``RetryHandler`` classification outcomes (raised error
identity, wrapped causes, exact diagnostic log lines) and the
``SSEClient`` DEBUG-level request/response context logging. Log lines are
asserted on their fully-rendered message so that re-cased, wrapped or
argument-dropping mutations fail.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import Mock, PropertyMock

import pytest
from curl_cffi.requests.exceptions import RequestException

from perplexity_cli.api.client import SSEClient
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
)
from perplexity_cli.utils.logging import redact_url


@pytest.fixture(autouse=True)
def t008_sleep_trace(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record retry sleeps and disable jitter for deterministic waits."""
    delays: list[float] = []
    monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
    monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", lambda *args: 0.0)
    return delays


def _http_error(
    status: int,
    *,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> tuple[PerplexityHTTPStatusError, Mock, Mock]:
    """Build an HTTP status error with sentinel request and response."""
    request = Mock(name="t008-request")
    response = Mock(name="t008-response")
    response.status_code = status
    response.headers = headers if headers is not None else {}
    response.text = text
    error = PerplexityHTTPStatusError(f"HTTP {status}", request=request, response=response)
    return error, request, response


def _client(max_retries: int = 3) -> SSEClient:
    return SSEClient(auth=AuthContext(token="t008-token"), max_retries=max_retries)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


class TestRetryHandlerClassification:
    """Raised-error identity and message contracts of RetryHandler."""

    def test_fresh_handler_has_no_pending_sleep_attempt(self) -> None:
        """A new handler reports no pending backoff attempt."""
        assert _client()._retry.consume_sleep_attempt() is None

    def test_401_preserves_request_and_response(self, caplog: pytest.LogCaptureFixture) -> None:
        """The 401 escalation keeps the original request/response binding."""
        error, request, response = _http_error(401)
        handler = _client()._retry

        with caplog.at_level(logging.ERROR, logger="perplexity_cli"):
            with pytest.raises(
                PerplexityHTTPStatusError, match=r"^Authentication failed\."
            ) as exc_info:
                handler.handle_http_error(error, 0)

        assert exc_info.value.request is request
        assert exc_info.value.response is response
        assert exc_info.value.__cause__ is error
        expected_log = f"HTTP 401 error (not retryable): {error}"
        assert expected_log in _messages(caplog)

    def test_403_retry_path_waits_and_records_attempt(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A 403 within budget returns the backoff wait and arms the sleeper."""
        error, _, _ = _http_error(403)
        handler = _client(max_retries=3)._retry

        with caplog.at_level(logging.WARNING, logger="perplexity_cli"):
            wait_time = handler.handle_http_error(error, 0)

        assert wait_time == 2.0
        assert handler.consume_sleep_attempt() == 1
        expected_log = "HTTP 403 error (may be Cloudflare blocking), retrying in 2.0s (attempt 2/3)"
        assert expected_log in _messages(caplog)

    def test_403_exhausted_preserves_bindings_and_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exhausted 403 raises with intact bindings and a final log."""
        error, request, response = _http_error(403)
        handler = _client(max_retries=1)._retry

        with caplog.at_level(logging.ERROR, logger="perplexity_cli"):
            with pytest.raises(PerplexityHTTPStatusError, match=r"^Access forbidden\.") as exc_info:
                handler.handle_http_error(error, 0)

        assert exc_info.value.request is request
        assert exc_info.value.response is response
        assert exc_info.value.__cause__ is error
        expected_log = f"HTTP 403 error (not retryable after 1 attempts): {error}"
        assert expected_log in _messages(caplog)

    def test_server_error_retry_path_logs_exact_wait(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A retryable 5xx announces the computed wait and attempt."""
        error, _, _ = _http_error(500)
        handler = _client(max_retries=3)._retry

        with caplog.at_level(logging.WARNING, logger="perplexity_cli"):
            wait_time = handler.handle_http_error(error, 0)

        assert wait_time == 2.0
        assert handler.consume_sleep_attempt() == 1
        expected_log = "HTTP 500 error, retrying in 2.0s (attempt 2/3)"
        assert expected_log in _messages(caplog)

    def test_429_exhausted_preserves_bindings_and_raises_rate_limit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exhausted 429 raises the rate-limit error with bindings kept."""
        error, request, response = _http_error(429)
        handler = _client(max_retries=1)._retry

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            with pytest.raises(
                PerplexityHTTPStatusError, match=r"^Rate limit exceeded\."
            ) as exc_info:
                handler.handle_http_error(error, 0)

        assert exc_info.value.request is request
        assert exc_info.value.response is response
        assert exc_info.value.__cause__ is error


class TestNetworkErrorHandling:
    """Network-error retry and wrap behaviour."""

    def test_transport_exception_retries_with_backoff(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A raw transport exception retries while attempts remain."""
        error = RequestException("t008-connection-reset")
        handler = _client(max_retries=3)._retry

        with caplog.at_level(logging.WARNING, logger="perplexity_cli"):
            wait_time = handler.handle_network_error(error, 0)

        assert wait_time == 2.0
        assert handler.consume_sleep_attempt() == 1
        expected_log = f"Network error, retrying in 2.0s (attempt 2/3): {error}"
        assert expected_log in _messages(caplog)

    def test_exhausted_transport_exception_wraps_with_cause(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exhausted transport exception is wrapped, keeping its cause."""
        error = RequestException("t008-connection-reset")
        handler = _client(max_retries=1)._retry

        with caplog.at_level(logging.ERROR, logger="perplexity_cli"):
            with pytest.raises(PerplexityRequestError) as exc_info:
                handler.handle_network_error(error, 0)

        assert str(exc_info.value) == str(error)
        assert exc_info.value.__cause__ is error
        expected_log = f"Network error after 1 attempts: {error}"
        assert expected_log in _messages(caplog)

    def test_exhausted_generic_error_reraises_original(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-transport errors are re-raised unchanged after exhaustion."""
        error = RuntimeError("t008-generic")
        handler = _client(max_retries=1)._retry

        with caplog.at_level(logging.ERROR, logger="perplexity_cli"):
            with pytest.raises(RuntimeError) as exc_info:
                handler.handle_network_error(error, 0)

        assert exc_info.value is error
        expected_log = f"Network error after 1 attempts: {error}"
        assert expected_log in _messages(caplog)


class TestHttpErrorContextLogging:
    """DEBUG diagnostics for HTTP error responses."""

    def test_context_logs_status_headers_and_redacted_body(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Error diagnostics carry status, Cloudflare metadata and preview."""
        error, _, _ = _http_error(
            503,
            headers={"cf-ray": "t008-ray", "cf-cache-status": "HIT"},
            text="t008-body",
        )
        handler = _client()._retry

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            handler._log_http_error_context(error)

        messages = _messages(caplog)
        assert f"HTTP Error 503: {error}" in messages
        assert "Cloudflare Ray ID: t008-ray" in messages
        assert "Cloudflare Cache Status: HIT" in messages
        previews = [m for m in messages if m.startswith("Response body preview: ")]
        assert len(previews) == 1
        assert "t008-body" not in previews[0]

    def test_context_body_preview_slices_at_five_hundred_chars(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The body preview is cut at exactly five hundred characters."""
        monkeypatch.setattr("perplexity_cli.api.client.redact_response_text", lambda value: value)
        error, _, _ = _http_error(500, text="A" * 600)
        handler = _client()._retry

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            handler._log_http_error_context(error)

        expected_preview = f"Response body preview: {'A' * 500}"
        assert expected_preview in _messages(caplog)

    def test_context_unreadable_body_logs_fallback(self, caplog: pytest.LogCaptureFixture) -> None:
        """Unreadable bodies produce the diagnostic fallback line."""
        error, _, response = _http_error(500)
        type(response).text = PropertyMock(side_effect=TypeError("unreadable"))
        handler = _client()._retry

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            handler._log_http_error_context(error)

        assert "Could not read response body for error diagnostics" in _messages(caplog)


class TestRequestContextLogging:
    """DEBUG diagnostics for outbound requests."""

    def _context(self) -> Any:
        from perplexity_cli.api.models import HttpRequestContext

        return HttpRequestContext(
            url="https://api.example.test/t008-query",
            headers={"Content-Type": "application/json"},
            effective_timeout=45,
        )

    def test_default_mode_logs_url_headers_auth_and_cookies(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Default requests log the URL, content type and auth presence."""
        client = SSEClient(
            auth=AuthContext(token="t008-bearer-sentinel"),
        )
        context = self._context()

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(context)

        messages = _messages(caplog)
        assert f"API Request to: {redact_url(context.url)}" in messages
        assert "Request headers: Content-Type=application/json" in messages
        assert any("Cookies: None" in message for message in messages)

    def test_default_mode_never_logs_token_value(self, caplog: pytest.LogCaptureFixture) -> None:
        """Only token presence is logged, never the token itself."""
        client = SSEClient(auth=AuthContext(token="t008-bearer-sentinel"))

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(self._context())

        joined = "\n".join(_messages(caplog))
        assert "Authentication: Bearer token present=True" in joined
        assert "t008-bearer-sentinel" not in joined

    def test_deep_research_mode_announces_extended_timeout(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Deep-research requests announce their extended timeout."""
        client = SSEClient(auth=AuthContext(token="t008-token"))

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(self._context(), query_mode="deep_research")

        assert "Deep research mode detected, timeout set to 45s" in _messages(caplog)

    def test_default_mode_never_announces_deep_research_timeout(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Standard requests stay silent about the extended timeout."""
        client = SSEClient(auth=AuthContext(token="t008-token"))

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(self._context())

        assert not any(
            message.startswith("Deep research mode detected") for message in _messages(caplog)
        )


class TestCookieContextLogging:
    """DEBUG diagnostics for cookie state."""

    def test_without_cookies_logs_absence(self, caplog: pytest.LogCaptureFixture) -> None:
        """No cookies produce the explicit absence line."""
        client = SSEClient(auth=AuthContext(token="t008-token"))

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_cookie_context()

        assert "Cookies: None (no Cloudflare bypass)" in _messages(caplog)

    def test_cookie_counts_distinguish_cloudflare_names(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cloudflare-prefixed cookies are counted separately."""
        client = SSEClient(
            auth=AuthContext(
                token="t008-token",
                cookies={
                    "cf_clearance": "t008-v1",
                    "__cf_bm": "t008-v2",
                    "session": "t008-v3",
                },
            )
        )

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_cookie_context()

        messages = _messages(caplog)
        assert "Cookies: 3 total, 2 Cloudflare-related" in messages
        presence = [
            message for message in messages if message.startswith("Cloudflare cookies present: ")
        ]
        assert len(presence) == 1
        assert "<redacted:3 keys>" in presence[0]


class TestResponseHeaderLogging:
    """DEBUG diagnostics for streaming responses."""

    def test_response_lines_label_status_and_cloudflare_headers(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Status plus each tracked header are logged under safe labels."""
        client = SSEClient(auth=AuthContext(token="t008-token"))
        response = Mock(status_code=207, reason="Partial")
        response.headers = {
            "cf-ray": "t008-ray",
            "cf-cache-status": "MISS",
            "server": "t008-server",
        }

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_response_headers(response)

        messages = _messages(caplog)
        assert "HTTP 207 Partial" in messages
        assert "Cloudflare Ray: t008-ray" in messages
        assert "Cloudflare Cache Status: MISS" in messages
        assert "Server: t008-server" in messages


class TestStreamRequestLoggingAndLoopBound:
    """Streaming execution logging and the retry loop boundary."""

    @staticmethod
    def _ok_stream_client(attempts: list[int]) -> tuple[SSEClient, Mock]:
        client = _client()
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {}
        mock_response.iter_lines.return_value = []
        stream_context = Mock()
        stream_context.__enter__ = Mock(return_value=mock_response)
        stream_context.__exit__ = Mock(return_value=False)
        session = Mock()

        def _record_stream(*args: object, **kwargs: object) -> Mock:
            attempts.append(len(args))
            return stream_context

        session.stream.side_effect = _record_stream
        client._client = session
        return client, session

    def test_successful_stream_logs_lifecycle_debug_lines(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A successful stream logs start, parsing and completion lines."""
        attempts: list[int] = []
        client, _ = self._ok_stream_client(attempts)

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            assert list(client.stream_post("https://api.example.test/s", {})) == []

        messages = _messages(caplog)
        assert (
            f"Streaming POST to {redact_url('https://api.example.test/s')} (attempt 1/3)"
            in messages
        )
        assert "Starting SSE stream parsing" in messages
        assert "SSE stream completed successfully" in messages

    def test_deep_research_payload_announces_mode(self, caplog: pytest.LogCaptureFixture) -> None:
        """Deep-research bodies emit the extended-timeout announcement."""
        attempts: list[int] = []
        client, _ = self._ok_stream_client(attempts)
        payload = {"params": {"search_implementation_mode": "multi_step"}}

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            assert list(client.stream_post("https://api.example.test/s", payload)) == []

        assert any(
            message.startswith("Deep research mode detected") for message in _messages(caplog)
        )

    def test_zero_max_retries_performs_no_attempts(self) -> None:
        """With retries disabled no transport call is ever made."""
        attempts: list[int] = []
        client, session = self._ok_stream_client(attempts)
        client.max_retries = 0

        assert list(client.stream_post("https://api.example.test/s", {})) == []
        assert session.stream.call_count == 0


class TestRetryStreamErrorTranslation:
    """Error-to-next-attempt translation for pre-output failures."""

    def test_returns_attempt_plus_one_for_retryable_network_error(
        self, t008_sleep_trace: list[float]
    ) -> None:
        """Retryable network failures advance the attempt counter by one."""
        client = _client(max_retries=3)

        next_attempt = client._retry_stream_error(PerplexityRequestError("t008-net"), 1)

        assert next_attempt == 2
        assert len(t008_sleep_trace) == 1
