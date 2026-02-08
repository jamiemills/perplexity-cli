"""Tests for API client module."""

import json
from unittest.mock import Mock

import httpx
import pytest

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

    def test_get_headers(self):
        """Test headers include Bearer authentication."""
        client = SSEClient(token="test-token-123")

        headers = client.get_headers()

        assert headers["Authorization"] == "Bearer test-token-123"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "text/event-stream"
        assert "User-Agent" in headers

    def test_parse_sse_stream_single_message(self):
        """Test parsing single SSE message."""
        client = SSEClient(token="test-token")

        # Mock response with SSE data
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
            "event: message",
            'data: {"msg": 1}',
            "",
            "event: message",
            'data: {"msg": 2}',
            "",
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
            "event: message",
            'data: {"line1":',
            'data: "value"}',
            "",
        ]

        messages = list(client._parse_sse_stream(mock_response))

        assert len(messages) == 1
        # Multi-line data joined with newlines
        expected_json = '{"line1":\n"value"}'
        assert messages[0] == json.loads(expected_json)

    def test_parse_sse_stream_invalid_json(self):
        """Test parsing invalid JSON raises ValueError."""
        client = SSEClient(token="test-token")

        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            "event: message",
            "data: {invalid json}",
            "",
        ]

        with pytest.raises(ValueError, match="Failed to parse SSE data"):
            list(client._parse_sse_stream(mock_response))

    def test_stream_post_success(self):
        """Test successful POST request with SSE streaming."""
        client = SSEClient(token="test-token")

        # Mock httpx client and response
        mock_response = Mock()
        mock_response.iter_lines.return_value = [
            "event: message",
            '{"status": "OK"}',
            "",
        ]
        mock_response.raise_for_status = Mock()

        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=mock_response)
        mock_stream_context.__exit__ = Mock(return_value=False)

        mock_http_client = Mock()
        mock_http_client.stream.return_value = mock_stream_context

        # Inject the mock client directly
        client._client = mock_http_client

        # Make request (consume iterator to trigger the call)
        list(client.stream_post("https://example.com/api", {"query": "test"}))

        # Verify request was made with correct headers
        mock_http_client.stream.assert_called_once()
        call_args = mock_http_client.stream.call_args
        assert call_args[0][0] == "POST"
        assert "Authorization" in call_args[1]["headers"]

    def test_stream_post_401_error(self):
        """Test 401 error handling."""
        client = SSEClient(token="invalid-token")

        # Mock 401 response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized",
            request=Mock(),
            response=mock_response,
        )

        mock_stream_context = Mock()
        mock_stream_context.__enter__ = Mock(return_value=mock_response)
        mock_stream_context.__exit__ = Mock(return_value=False)

        mock_http_client = Mock()
        mock_http_client.stream.return_value = mock_stream_context

        # Inject the mock client directly
        client._client = mock_http_client

        # Should raise HTTPStatusError with helpful message
        with pytest.raises(httpx.HTTPStatusError, match="Authentication failed"):
            list(client.stream_post("https://example.com/api", {}))

    def test_sse_client_creates_client_lazily(self):
        """Test that _client is None after init and created on first _get_client() call."""
        client = SSEClient(token="test-token")
        assert client._client is None

        http_client = client._get_client()
        assert http_client is not None
        assert isinstance(http_client, httpx.Client)

        client.close()

    def test_sse_client_reuses_client(self):
        """Test that two _get_client() calls return the same object."""
        client = SSEClient(token="test-token")

        http_client_1 = client._get_client()
        http_client_2 = client._get_client()
        assert http_client_1 is http_client_2

        client.close()

    def test_sse_client_close(self):
        """Test that close() calls client.close() and resets _client to None."""
        client = SSEClient(token="test-token")

        mock_http_client = Mock()
        client._client = mock_http_client

        client.close()

        mock_http_client.close.assert_called_once()
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
