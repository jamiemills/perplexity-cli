"""Tests for API client stream retry behaviour."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from curl_cffi.requests.exceptions import RequestException

from perplexity_cli.api.client import SSEClient
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)


@pytest.fixture
def retry_sleep_trace(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr("perplexity_cli.utils.retry.time.sleep", delays.append)
    monkeypatch.setattr("perplexity_cli.utils.retry._rng.uniform", lambda *args: 0.0)
    return delays


class TestStreamRetry:
    """End-to-end retry boundaries for stream_post."""

    @staticmethod
    def _stream_context(response: Mock) -> Mock:
        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=response)
        mock_stream_context.__exit__ = Mock(return_value=False)
        return mock_stream_context

    @staticmethod
    def _ok_response(lines: object = None) -> Mock:
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {}
        mock_response.iter_lines.return_value = lines or [b'data: {"status": "OK"}', b""]
        return mock_response

    @staticmethod
    def _error_response(status: int) -> Mock:
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = status
        mock_response.reason = "Error"
        mock_response.url = "https://example.com/api"
        mock_response.headers = {}
        mock_response.content = b"error"
        return mock_response

    def test_raw_curl_failure_retries_and_succeeds(self, retry_sleep_trace: list[float]) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.side_effect = [
            RequestException("connection reset"),
            self._stream_context(self._ok_response()),
        ]
        client._client = mock_session

        results = list(client.stream_post("https://example.com/api", {"query": "test"}))

        assert results == [{"status": "OK"}]
        assert mock_session.stream.call_count == 2
        assert retry_sleep_trace == [2.0]

    def test_raw_curl_exhaustion_raises_with_cause(self, retry_sleep_trace: list[float]) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=2)
        mock_session = Mock()
        mock_session.stream.side_effect = RequestException("connection reset")
        client._client = mock_session

        with pytest.raises(PerplexityRequestError) as exc_info:
            list(client.stream_post("https://example.com/api", {"query": "test"}))

        assert isinstance(exc_info.value.__cause__, RequestException)
        assert mock_session.stream.call_count == 2
        assert retry_sleep_trace == [2.0]

    def test_wrapped_request_error_retries_and_succeeds(
        self, retry_sleep_trace: list[float]
    ) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.side_effect = [
            PerplexityRequestError("timeout"),
            self._stream_context(self._ok_response()),
        ]
        client._client = mock_session

        results = list(client.stream_post("https://example.com/api", {"query": "test"}))

        assert results == [{"status": "OK"}]
        assert mock_session.stream.call_count == 2
        assert retry_sleep_trace == [2.0]

    def test_no_retry_after_event_yielded(self) -> None:
        def flaky_lines():
            yield b'data: {"status": "partial"}'
            yield b""
            raise RequestException("connection reset")

        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.return_value = self._stream_context(self._ok_response(flaky_lines()))
        client._client = mock_session

        generator = client.stream_post("https://example.com/api", {"query": "test"})
        assert next(generator)["status"] == "partial"
        with pytest.raises(RequestException):
            next(generator)
        assert mock_session.stream.call_count == 1

    def test_schema_error_never_retries(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.return_value = self._stream_context(
            self._ok_response([b"data: {invalid json}", b""])
        )
        client._client = mock_session

        with pytest.raises(UpstreamSchemaError):
            list(client.stream_post("https://example.com/api", {"query": "test"}))
        assert mock_session.stream.call_count == 1

    def test_401_raises_immediately(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.return_value = self._stream_context(self._error_response(401))
        client._client = mock_session

        with pytest.raises(PerplexityHTTPStatusError):
            list(client.stream_post("https://example.com/api", {"query": "test"}))
        assert mock_session.stream.call_count == 1

    @pytest.mark.parametrize("status", [403, 429, 500])
    def test_retryable_status_retries_then_succeeds(
        self, status: int, retry_sleep_trace: list[float]
    ) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.side_effect = [
            self._stream_context(self._error_response(status)),
            self._stream_context(self._ok_response()),
        ]
        client._client = mock_session

        results = list(client.stream_post("https://example.com/api", {"query": "test"}))

        assert results == [{"status": "OK"}]
        assert mock_session.stream.call_count == 2
        assert retry_sleep_trace == [2.0]

    def test_429_retry_after_exact_delay(self, retry_sleep_trace: list[float]) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        error_response = self._error_response(429)
        error_response.headers = {"Retry-After": "2.5"}
        mock_session = Mock()
        mock_session.stream.side_effect = [
            self._stream_context(error_response),
            self._stream_context(self._ok_response()),
        ]
        client._client = mock_session

        results = list(client.stream_post("https://example.com/api", {"query": "test"}))

        assert results == [{"status": "OK"}]
        assert mock_session.stream.call_count == 2
        assert retry_sleep_trace == [2.5]

    def test_keyboard_interrupt_propagates(self) -> None:
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        mock_session = Mock()
        mock_session.stream.side_effect = KeyboardInterrupt()
        client._client = mock_session

        with pytest.raises(KeyboardInterrupt):
            list(client.stream_post("https://example.com/api", {"query": "test"}))
        assert mock_session.stream.call_count == 1
