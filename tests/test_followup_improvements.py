"""Additional tests for follow-up query improvements.

These tests verify enhanced error handling and validation.
"""

import pytest
from unittest.mock import MagicMock, patch

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import ThreadContext


class TestFollowupImprovements:
    """Test improvements to follow-up query implementation."""

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_validates_frontend_context_uuid(self, mock_client_class):
        """Test that submit_followup_query validates frontend_context_uuid is present."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        
        api = PerplexityAPI(token="test-token")
        
        # ThreadContext without frontend_context_uuid should raise ValueError
        invalid_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="",  # Empty - should fail
            context_uuid="context-uuid",
        )
        
        with pytest.raises(ValueError, match="frontend_context_uuid"):
            list(api.submit_followup_query("test query", invalid_context))

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_with_all_context_fields(self, mock_client_class):
        """Test that submit_followup_query includes all context fields when present."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        
        # Mock stream_post to return empty iterator
        mock_client.stream_post.return_value = iter([])
        
        api = PerplexityAPI(token="test-token")
        thread_context = ThreadContext(
            thread_url_slug="test-slug-123",
            frontend_context_uuid="frontend-uuid-123",
            context_uuid="context-uuid-123",
            read_write_token="token-123",
        )
        
        # Call submit_followup_query
        list(api.submit_followup_query("test query", thread_context))
        
        # Verify stream_post was called
        assert mock_client.stream_post.called
        
        # Get the request data that was passed
        call_args = mock_client.stream_post.call_args
        request_data = call_args[0][1]  # Second positional argument
        params = request_data["params"]
        
        # Verify all context fields are included
        assert params["is_related_query"] is True
        assert params["frontend_context_uuid"] == "frontend-uuid-123"
        assert params["context_uuid"] == "context-uuid-123"
        assert params["read_write_token"] == "token-123"
        assert params["thread_url_slug"] == "test-slug-123"

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_with_partial_context_fields(self, mock_client_class):
        """Test that submit_followup_query works with partial context fields."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        
        # Mock stream_post to return empty iterator
        mock_client.stream_post.return_value = iter([])
        
        api = PerplexityAPI(token="test-token")
        # ThreadContext with only frontend_context_uuid (minimum required)
        thread_context = ThreadContext(
            thread_url_slug="",
            frontend_context_uuid="frontend-uuid-123",
            context_uuid=None,
            read_write_token=None,
        )
        
        # Should not raise error (frontend_context_uuid is present)
        list(api.submit_followup_query("test query", thread_context))
        
        # Verify stream_post was called
        assert mock_client.stream_post.called
        
        # Get the request data
        call_args = mock_client.stream_post.call_args
        request_data = call_args[0][1]
        params = request_data["params"]
        
        # Verify frontend_context_uuid is included
        assert params["frontend_context_uuid"] == "frontend-uuid-123"
        assert params["is_related_query"] is True
        
        # Optional fields should not be included if None
        assert "context_uuid" not in params or params.get("context_uuid") is None
        assert "read_write_token" not in params or params.get("read_write_token") is None
        assert "thread_url_slug" not in params or params.get("thread_url_slug") is None

