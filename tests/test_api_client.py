"""Tests for API client module."""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock

import pytest
from curl_cffi.requests import Session

from perplexity_cli.api.client import SSEClient, SSEParser
from perplexity_cli.api.models import Block, QueryParams, QueryRequest, SSEMessage, WebResult
from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import setup_logging


class TestQueryParams:
    """Tests for QueryParams model."""

    def test_default_values(self):
        """Test QueryParams has correct default values."""
        params = QueryParams()

        assert params.language == "en-US"
        assert params.timezone == "Europe/London"
        assert params.search_focus == "internet"
        assert params.mode == "copilot"
        assert params.version == "2.18"
        assert params.sources == ["web"]

    def test_to_dict(self):
        """Test QueryParams converts to dictionary."""
        params = QueryParams(frontend_uuid="test-uuid-1", frontend_context_uuid="test-uuid-2")

        data = params.to_dict()

        assert isinstance(data, dict)
        assert data["frontend_uuid"] == "test-uuid-1"
        assert data["frontend_context_uuid"] == "test-uuid-2"
        assert data["language"] == "en-US"
        assert data["version"] == "2.18"


class TestQueryRequest:
    """Tests for QueryRequest model."""

    def test_to_dict(self):
        """Test QueryRequest converts to dictionary."""
        params = QueryParams(frontend_uuid="uuid1", frontend_context_uuid="uuid2")
        request = QueryRequest(query_str="What is AI?", params=params)

        data = request.to_dict()

        assert data["query_str"] == "What is AI?"
        assert "params" in data
        assert data["params"]["frontend_uuid"] == "uuid1"


class TestWebResult:
    """Tests for WebResult model."""

    def test_from_dict(self):
        """Test WebResult creation from dictionary."""
        data = {
            "name": "Test Article",
            "url": "https://example.com",
            "snippet": "Test snippet text",
            "timestamp": "2025-01-01T00:00:00",
        }

        result = WebResult.model_validate(data)

        assert result.name == "Test Article"
        assert result.url == "https://example.com"
        assert result.snippet == "Test snippet text"
        assert result.timestamp == "2025-01-01T00:00:00"

    def test_from_dict_minimal(self):
        """Test WebResult with minimal fields."""
        data = {"name": "Article", "url": "https://example.com", "snippet": "Snippet"}

        result = WebResult.model_validate(data)

        assert result.name == "Article"
        assert result.timestamp is None


class TestBlock:
    """Tests for Block model."""

    def test_from_dict(self):
        """Test Block creation from dictionary."""
        data = {
            "intended_usage": "web_results",
            "web_result_block": {"web_results": []},
        }

        block = Block.model_validate(data)

        assert block.intended_usage == "web_results"
        assert "web_result_block" in block.content

    def test_extract_text_from_markdown_block(self):
        """Test block text extraction from markdown chunks."""
        block = Block(
            intended_usage="ask_text",
            content={"markdown_block": {"chunks": ["Hello ", "world"]}},
        )

        assert block.extract_text() == "Hello world"

    def test_extract_plan_info(self):
        """Test plan metadata extraction from plan block."""
        block = Block(
            intended_usage="plan",
            content={
                "plan_block": {
                    "progress": "Researching",
                    "eta_seconds_remaining": 42,
                    "goals": ["Goal A"],
                    "pct_complete": 50,
                }
            },
        )

        assert block.extract_plan_info() == {
            "progress": "Researching",
            "eta_seconds": 42,
            "goals": ["Goal A"],
            "pct_complete": 50,
        }

    def test_extract_web_results(self):
        """Test block web result extraction."""
        block = Block(
            intended_usage="web_results",
            content={
                "web_result_block": {
                    "web_results": [
                        {"name": "Example", "url": "https://example.com", "snippet": "Snippet"}
                    ]
                }
            },
        )

        results = block.extract_web_results()

        assert results is not None
        assert len(results) == 1
        assert results[0].url == "https://example.com"


class TestSSEMessage:
    """Tests for SSEMessage model."""

    def test_from_dict(self):
        """Test SSEMessage creation from dictionary."""
        data = {
            "backend_uuid": "backend-123",
            "context_uuid": "context-456",
            "uuid": "request-789",
            "frontend_context_uuid": "frontend-abc",
            "display_model": "pplx_pro",
            "mode": "COPILOT",
            "thread_url_slug": "test-thread",
            "status": "COMPLETE",
            "text_completed": True,
            "blocks": [{"intended_usage": "answer", "text": "Test answer"}],
            "final_sse_message": True,
        }

        message = SSEMessage.model_validate(data)

        assert message.backend_uuid == "backend-123"
        assert message.status == "COMPLETE"
        assert message.text_completed is True
        assert message.final_sse_message is True
        assert len(message.blocks) == 1

    def test_extract_answer_text(self):
        """Test answer text extraction from ask_text blocks."""
        message = SSEMessage.model_validate(
            {
                "backend_uuid": "backend-123",
                "context_uuid": "context-456",
                "uuid": "request-789",
                "frontend_context_uuid": "frontend-abc",
                "display_model": "pplx_pro",
                "mode": "COPILOT",
                "status": "COMPLETE",
                "text_completed": True,
                "blocks": [
                    {"intended_usage": "ask_text", "markdown_block": {"chunks": ["Answer"]}}
                ],
                "final_sse_message": True,
            }
        )

        assert message.extract_answer_text() == "Answer"


class TestSSEClient:
    """Tests for SSEClient."""

    def test_get_headers_without_cookies(self):
        """Test headers include Bearer authentication but no User-Agent or Cookie."""
        client = SSEClient(auth=AuthContext(token="test-token-123"))

        headers = client.get_headers()

        assert headers["Authorization"] == "Bearer test-token-123"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "text/event-stream"
        # curl_cffi sets User-Agent automatically via impersonation
        assert "User-Agent" not in headers
        # No cookies, so no CSRF token
        assert "X-CSRFToken" not in headers

    def test_get_headers_with_csrf_cookie(self):
        """Test that X-CSRFToken header is set from csrftoken cookie."""
        client = SSEClient(auth=AuthContext(token="test-token", cookies={"csrftoken": "abc123"}))

        headers = client.get_headers()

        assert headers["X-CSRFToken"] == "abc123"

    def test_get_headers_with_cookies_no_csrf(self):
        """Test that cookies without csrftoken do not produce X-CSRFToken."""
        client = SSEClient(auth=AuthContext(token="test-token", cookies={"cf_clearance": "xyz"}))

        headers = client.get_headers()

        assert "X-CSRFToken" not in headers

    def test_parse_sse_stream_single_message(self):
        """Test parsing single SSE message with bytes input."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"test": "value"}',
            b"",
        ]

        messages = list(SSEParser.parse(mock_response, client.logger))

        assert len(messages) == 1
        assert messages[0]["test"] == "value"

    def test_parse_sse_stream_string_input(self):
        """Test parsing SSE message with string input (backward compatibility)."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            "event: message",
            'data: {"test": "value"}',
            "",
        ]

        messages = list(SSEParser.parse(mock_response, client.logger))

        assert len(messages) == 1
        assert messages[0]["test"] == "value"

    def test_parse_sse_stream_multiple_messages(self):
        """Test parsing multiple SSE messages."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"msg": 1}',
            b"",
            b"event: message",
            b'data: {"msg": 2}',
            b"",
        ]

        messages = list(SSEParser.parse(mock_response, client.logger))

        assert len(messages) == 2
        assert messages[0]["msg"] == 1
        assert messages[1]["msg"] == 2

    def test_parse_sse_stream_multiline_data(self):
        """Test parsing SSE message with multi-line data."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"line1":',
            b'data: "value"}',
            b"",
        ]

        messages = list(SSEParser.parse(mock_response, client.logger))

        assert len(messages) == 1
        expected_json = '{"line1":\n"value"}'
        assert messages[0] == json.loads(expected_json)

    def test_parse_sse_stream_invalid_json(self):
        """Test parsing invalid JSON raises UpstreamSchemaError."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b"data: {invalid json}",
            b"",
        ]

        with pytest.raises(UpstreamSchemaError, match="Failed to parse SSE data"):
            list(SSEParser.parse(mock_response, client.logger))

    def test_sse_message_from_dict_rejects_non_dict(self):
        """Test malformed SSE payloads raise UpstreamSchemaError."""
        with pytest.raises(UpstreamSchemaError, match="Malformed SSE blocks"):
            SSEMessage.model_validate({"blocks": {}})

    def test_stream_post_success(self):
        """Test successful POST request with SSE streaming."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        # Mock curl_cffi response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.reason = "OK"
        mock_response.headers = {}
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"status": "OK"}',
            b"",
        ]

        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=mock_response)
        mock_stream_context.__exit__ = Mock(return_value=False)

        mock_session = Mock()
        mock_session.stream.return_value = mock_stream_context

        client._client = mock_session

        results = list(client.stream_post("https://example.com/api", {"query": "test"}))

        assert len(results) == 1
        assert results[0]["status"] == "OK"

        mock_session.stream.assert_called_once()
        call_args = mock_session.stream.call_args
        assert call_args[0][0] == "POST"
        assert "Authorization" in call_args[1]["headers"]
        # Cookies passed as separate parameter
        assert "cookies" in call_args[1]

    def test_stream_post_401_error(self):
        """Test 401 error raises PerplexityHTTPStatusError."""
        client = SSEClient(auth=AuthContext(token="invalid-token"))

        # Mock a 401 response from curl_cffi
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 401
        mock_response.reason = "Unauthorized"
        mock_response.url = "https://example.com/api"
        mock_response.headers = {}
        mock_response.content = b"Unauthorized"

        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=mock_response)
        mock_stream_context.__exit__ = Mock(return_value=False)

        mock_session = Mock()
        mock_session.stream.return_value = mock_stream_context

        client._client = mock_session

        with pytest.raises(PerplexityHTTPStatusError, match="Authentication failed"):
            list(client.stream_post("https://example.com/api", {}))

    def test_stream_post_403_error_retries(self):
        """Test 403 error triggers retries with backoff."""
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=2)

        # Mock a 403 response from curl_cffi
        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.reason = "Forbidden"
        mock_response.url = "https://example.com/api"
        mock_response.headers = {}
        mock_response.content = b"Forbidden"

        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=mock_response)
        mock_stream_context.__exit__ = Mock(return_value=False)

        mock_session = Mock()
        mock_session.stream.return_value = mock_stream_context

        client._client = mock_session

        with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
            list(client.stream_post("https://example.com/api", {}))

        # Should have retried (2 calls total for max_retries=2)
        assert mock_session.stream.call_count == 2

    def test_stream_post_debug_logging_redacts_sensitive_values(self, caplog):
        """Test debug logs do not expose cookie names or response bodies."""
        client = SSEClient(
            auth=AuthContext(
                token="test-token",
                cookies={"cf_clearance": "secret-cookie", "csrftoken": "secret-csrf"},
            ),
            max_retries=1,
        )

        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.reason = "Forbidden"
        mock_response.url = "https://example.com/api"
        mock_response.headers = {"cf-ray": "ray-id"}
        mock_response.content = b'{"secret":"value"}'
        mock_response.text = '{"secret":"value"}'

        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=mock_response)
        mock_stream_context.__exit__ = Mock(return_value=False)

        mock_session = Mock()
        mock_session.stream.return_value = mock_stream_context
        client._client = mock_session

        setup_logging(debug=True)

        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            with pytest.raises(PerplexityHTTPStatusError, match="Access forbidden"):
                list(client.stream_post("https://example.com/api", {}))

        combined = "\n".join(record.getMessage() for record in caplog.records)
        assert "cf_clearance" not in combined
        assert "secret-cookie" not in combined
        assert '{"secret":"value"}' not in combined
        assert "<redacted:2 keys>" in combined

    def test_raise_http_status_error(self):
        """Test raise_http_status_error constructs valid custom exceptions."""
        from perplexity_cli.utils.http_errors import raise_http_status_error

        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.reason = "Internal Server Error"
        mock_response.url = "https://example.com/api"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.content = b"Server error"

        with pytest.raises(PerplexityHTTPStatusError) as exc_info:
            raise_http_status_error(mock_response)

        error = exc_info.value
        assert error.response.status_code == 500
        assert error.response.text == "Server error"

    def test_sse_client_creates_client_lazily(self):
        """Test that _client is None after init and created on first _get_client() call."""
        client = SSEClient(auth=AuthContext(token="test-token"))
        assert client._client is None

        session = client._get_client()
        assert session is not None
        assert isinstance(session, Session)

        client.close()

    def test_sse_client_reuses_client(self):
        """Test that two _get_client() calls return the same object."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        session_1 = client._get_client()
        session_2 = client._get_client()
        assert session_1 is session_2

        client.close()

    def test_sse_client_close(self):
        """Test that close() calls client.close() and resets _client to None."""
        client = SSEClient(auth=AuthContext(token="test-token"))

        mock_session = Mock()
        client._client = mock_session

        client.close()

        mock_session.close.assert_called_once()
        assert client._client is None

    def test_sse_client_close_when_no_client(self):
        """Test that close() is safe when no client exists."""
        client = SSEClient(auth=AuthContext(token="test-token"))
        assert client._client is None

        # Should not raise
        client.close()
        assert client._client is None


class TestPerplexityAPIContextManager:
    """Tests for PerplexityAPI context manager protocol."""

    def test_context_manager_enter_returns_self(self):
        """Test that __enter__ returns the PerplexityAPI instance."""
        from perplexity_cli.api.endpoints import PerplexityAPI

        api = PerplexityAPI(token="test-token")
        result = api.__enter__()
        assert result is api
        api.__exit__(None, None, None)

    def test_context_manager_exit_calls_close(self):
        """Test that __exit__ calls close()."""
        from perplexity_cli.api.endpoints import PerplexityAPI

        api = PerplexityAPI(token="test-token")
        api.client = Mock()

        api.__exit__(None, None, None)

        api.client.close.assert_called_once()


class TestResolveEffectiveTimeout:
    """Tests for _resolve_effective_timeout."""

    def test_deep_research_timeout(self):
        """Deep research queries use the extended timeout."""
        client = SSEClient(auth=AuthContext(token="test-token"))
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"search_implementation_mode": "multi_step"}}
        )
        assert is_deep is True
        assert timeout == 360

    def test_standard_timeout(self):
        """Non-deep-research queries use the standard timeout."""
        client = SSEClient(auth=AuthContext(token="test-token"), timeout=45)
        is_deep, timeout = client._resolve_effective_timeout({"params": {}})
        assert is_deep is False
        assert timeout == 45

    def test_research_override_timeout(self):
        """Research workflow overrides also use the extended timeout."""
        client = SSEClient(auth=AuthContext(token="test-token"), timeout=45)
        is_deep, timeout = client._resolve_effective_timeout(
            {"params": {"workflow_key": "deep_research"}}
        )
        assert is_deep is True
        assert timeout == 360


class TestLogRequestContext:
    """Tests for _log_request_context."""

    def test_deep_research_debug_log(self, caplog):
        """Deep research mode emits a specific debug log line."""
        setup_logging(debug=True)
        client = SSEClient(auth=AuthContext(token="test-token"))

        from perplexity_cli.api.models import HttpRequestContext

        ctx = HttpRequestContext(
            url="https://example.com/api",
            headers={"Content-Type": "application/json"},
            effective_timeout=360,
        )
        with caplog.at_level(logging.DEBUG, logger="perplexity_cli"):
            client._log_request_context(ctx, is_deep_research=True)

        assert any("Deep research mode" in r.getMessage() for r in caplog.records)


class TestHandleRetryableError:
    """Tests for _handle_retryable_error via RetryHandler."""

    def _make_http_error(self, status: int) -> PerplexityHTTPStatusError:
        """Create a mock HTTP status error."""
        mock_response = Mock()
        mock_response.status_code = status
        mock_response.headers = {}
        return PerplexityHTTPStatusError(f"HTTP {status}", request=Mock(), response=mock_response)

    def test_retryable_500_returns_wait_time(self):
        """A 500 error with remaining retries returns a wait time."""
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        error = self._make_http_error(500)
        wait = client._retry._handle_retryable_error(error, attempt=0)
        assert isinstance(wait, float) or isinstance(wait, int)
        assert wait > 0

    def test_retryable_429_exhausted_raises(self):
        """A 429 error with exhausted retries raises rate limit message."""
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=1)
        error = self._make_http_error(429)
        with pytest.raises(PerplexityHTTPStatusError, match="Rate limit"):
            client._retry._handle_retryable_error(error, attempt=0)

    def test_non_retryable_reraises(self):
        """A non-retryable status re-raises the original error."""
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        error = self._make_http_error(400)
        with pytest.raises(PerplexityHTTPStatusError):
            client._retry._handle_retryable_error(error, attempt=0)


class TestHandleNetworkError:
    """Tests for _handle_network_error via RetryHandler."""

    def test_request_exception_converts_to_perplexity_error(self):
        """curl_cffi RequestException is converted to PerplexityRequestError."""
        from curl_cffi.requests.exceptions import RequestException

        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        error = RequestException("connection failed")

        with pytest.raises(PerplexityRequestError, match="connection failed"):
            client._retry.handle_network_error(error, attempt=0)

    def test_retryable_perplexity_error_increments_attempt(self):
        """A retryable PerplexityRequestError returns incremented attempt."""
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=3)
        error = PerplexityRequestError("timeout")

        result = client._retry.handle_network_error(error, attempt=0)
        assert result == 1

    def test_non_retryable_after_exhaustion_raises(self):
        """When retries are exhausted, the error is re-raised."""
        client = SSEClient(auth=AuthContext(token="test-token"), max_retries=1)
        error = PerplexityRequestError("timeout")

        with pytest.raises(PerplexityRequestError):
            client._retry.handle_network_error(error, attempt=0)


class TestParseSSEStreamFinalEvent:
    """Tests for SSEParser.parse final event without trailing empty line."""

    def test_final_event_without_trailing_empty_line(self):
        """Stream ending without an empty line still yields the final event."""
        client = SSEClient(auth=AuthContext(token="test-token"))
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"final": true}',
        ]

        messages = list(SSEParser.parse(mock_response, client.logger))
        assert len(messages) == 1
        assert messages[0]["final"] is True
