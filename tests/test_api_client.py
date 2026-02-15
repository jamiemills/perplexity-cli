"""Tests for API client module."""

import json
from unittest.mock import Mock

import httpx
import pytest
from curl_cffi.requests import Session

from perplexity_cli.api.client import SSEClient
from perplexity_cli.api.models import Block, QueryParams, QueryRequest, SSEMessage, WebResult


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

        result = WebResult.from_dict(data)

        assert result.name == "Test Article"
        assert result.url == "https://example.com"
        assert result.snippet == "Test snippet text"
        assert result.timestamp == "2025-01-01T00:00:00"

    def test_from_dict_minimal(self):
        """Test WebResult with minimal fields."""
        data = {"name": "Article", "url": "https://example.com", "snippet": "Snippet"}

        result = WebResult.from_dict(data)

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

        block = Block.from_dict(data)

        assert block.intended_usage == "web_results"
        assert "web_result_block" in block.content


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

        message = SSEMessage.from_dict(data)

        assert message.backend_uuid == "backend-123"
        assert message.status == "COMPLETE"
        assert message.text_completed is True
        assert message.final_sse_message is True
        assert len(message.blocks) == 1


class TestSSEClient:
    """Tests for SSEClient."""

    def test_get_headers_without_cookies(self):
        """Test headers include Bearer authentication but no User-Agent or Cookie."""
        client = SSEClient(token="test-token-123")

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
        client = SSEClient(token="test-token", cookies={"csrftoken": "abc123"})

        headers = client.get_headers()

        assert headers["X-CSRFToken"] == "abc123"

    def test_get_headers_with_cookies_no_csrf(self):
        """Test that cookies without csrftoken do not produce X-CSRFToken."""
        client = SSEClient(token="test-token", cookies={"cf_clearance": "xyz"})

        headers = client.get_headers()

        assert "X-CSRFToken" not in headers

    def test_parse_sse_stream_single_message(self):
        """Test parsing single SSE message with bytes input."""
        client = SSEClient(token="test-token")

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"test": "value"}',
            b"",
        ]

        messages = list(client._parse_sse_stream(mock_response))

        assert len(messages) == 1
        assert messages[0]["test"] == "value"

    def test_parse_sse_stream_string_input(self):
        """Test parsing SSE message with string input (backward compatibility)."""
        client = SSEClient(token="test-token")

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            "event: message",
            'data: {"test": "value"}',
            "",
        ]

        messages = list(client._parse_sse_stream(mock_response))

        assert len(messages) == 1
        assert messages[0]["test"] == "value"

    def test_parse_sse_stream_multiple_messages(self):
        """Test parsing multiple SSE messages."""
        client = SSEClient(token="test-token")

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"msg": 1}',
            b"",
            b"event: message",
            b'data: {"msg": 2}',
            b"",
        ]

        messages = list(client._parse_sse_stream(mock_response))

        assert len(messages) == 2
        assert messages[0]["msg"] == 1
        assert messages[1]["msg"] == 2

    def test_parse_sse_stream_multiline_data(self):
        """Test parsing SSE message with multi-line data."""
        client = SSEClient(token="test-token")

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b'data: {"line1":',
            b'data: "value"}',
            b"",
        ]

        messages = list(client._parse_sse_stream(mock_response))

        assert len(messages) == 1
        expected_json = '{"line1":\n"value"}'
        assert messages[0] == json.loads(expected_json)

    def test_parse_sse_stream_invalid_json(self):
        """Test parsing invalid JSON raises ValueError."""
        client = SSEClient(token="test-token")

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            b"event: message",
            b"data: {invalid json}",
            b"",
        ]

        with pytest.raises(ValueError, match="Failed to parse SSE data"):
            list(client._parse_sse_stream(mock_response))

    def test_stream_post_success(self):
        """Test successful POST request with SSE streaming."""
        client = SSEClient(token="test-token")

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
        """Test 401 error raises httpx.HTTPStatusError."""
        client = SSEClient(token="invalid-token")

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

        with pytest.raises(httpx.HTTPStatusError, match="Authentication failed"):
            list(client.stream_post("https://example.com/api", {}))

    def test_stream_post_403_error_retries(self):
        """Test 403 error triggers retries with backoff."""
        client = SSEClient(token="test-token", max_retries=2)

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

        with pytest.raises(httpx.HTTPStatusError, match="Access forbidden"):
            list(client.stream_post("https://example.com/api", {}))

        # Should have retried (2 calls total for max_retries=2)
        assert mock_session.stream.call_count == 2

    def test_raise_http_status_error(self):
        """Test _raise_http_status_error constructs valid httpx exceptions."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.reason = "Internal Server Error"
        mock_response.url = "https://example.com/api"
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.content = b"Server error"

        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            SSEClient._raise_http_status_error(mock_response)

        error = exc_info.value
        assert error.response.status_code == 500
        assert error.response.text == "Server error"

    def test_sse_client_creates_client_lazily(self):
        """Test that _client is None after init and created on first _get_client() call."""
        client = SSEClient(token="test-token")
        assert client._client is None

        session = client._get_client()
        assert session is not None
        assert isinstance(session, Session)

        client.close()

    def test_sse_client_reuses_client(self):
        """Test that two _get_client() calls return the same object."""
        client = SSEClient(token="test-token")

        session_1 = client._get_client()
        session_2 = client._get_client()
        assert session_1 is session_2

        client.close()

    def test_sse_client_close(self):
        """Test that close() calls client.close() and resets _client to None."""
        client = SSEClient(token="test-token")

        mock_session = Mock()
        client._client = mock_session

        client.close()

        mock_session.close.assert_called_once()
        assert client._client is None

    def test_sse_client_close_when_no_client(self):
        """Test that close() is safe when no client exists."""
        client = SSEClient(token="test-token")
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
