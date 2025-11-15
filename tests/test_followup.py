"""Tests for follow-up query functionality and thread context."""

from unittest.mock import MagicMock, patch

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import SSEMessage, ThreadContext
from perplexity_cli.utils.thread_context import (
    clear_thread_context,
    load_thread_context,
    save_thread_context,
)


class TestThreadContextExtraction:
    """Test thread context extraction from SSE messages."""

    def test_extract_thread_context_from_final_message(self):
        """Test extracting thread context from final SSE message."""
        api = PerplexityAPI(token="test-token")
        
        messages = [
            SSEMessage(
                backend_uuid="backend-1",
                context_uuid="context-1",
                uuid="uuid-1",
                frontend_context_uuid="frontend-1",
                display_model="pplx_pro",
                mode="copilot",
                thread_url_slug=None,
                status="processing",
                text_completed=False,
                blocks=[],
                final_sse_message=False,
            ),
            SSEMessage(
                backend_uuid="backend-2",
                context_uuid="context-2",
                uuid="uuid-2",
                frontend_context_uuid="frontend-2",
                display_model="pplx_pro",
                mode="copilot",
                thread_url_slug="test-slug",
                status="completed",
                text_completed=True,
                blocks=[],
                final_sse_message=True,
                read_write_token="token-123",
            ),
        ]
        
        context = api.extract_thread_context(messages)
        assert context is not None
        assert context.thread_url_slug == "test-slug"
        assert context.frontend_context_uuid == "frontend-2"
        assert context.context_uuid == "context-2"
        assert context.read_write_token == "token-123"

    def test_extract_thread_context_no_final_message(self):
        """Test extracting context when no final message has thread_url_slug."""
        api = PerplexityAPI(token="test-token")
        
        messages = [
            SSEMessage(
                backend_uuid="backend-1",
                context_uuid="context-1",
                uuid="uuid-1",
                frontend_context_uuid="frontend-1",
                display_model="pplx_pro",
                mode="copilot",
                thread_url_slug=None,
                status="processing",
                text_completed=False,
                blocks=[],
                final_sse_message=True,
            ),
        ]
        
        context = api.extract_thread_context(messages)
        assert context is None

    def test_extract_thread_context_empty_list(self):
        """Test extracting context from empty message list."""
        api = PerplexityAPI(token="test-token")
        context = api.extract_thread_context([])
        assert context is None


class TestFollowupQuery:
    """Test follow-up query functionality."""

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_sets_is_related_query(self, mock_client_class):
        """Test that submit_followup_query sets is_related_query=True."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        
        # Mock stream_post to return empty iterator
        mock_client.stream_post.return_value = iter([])
        
        api = PerplexityAPI(token="test-token")
        thread_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="context-uuid",
        )
        
        # Call submit_followup_query
        list(api.submit_followup_query("test query", thread_context))
        
        # Verify stream_post was called
        assert mock_client.stream_post.called
        
        # Get the request data that was passed
        call_args = mock_client.stream_post.call_args
        request_data = call_args[0][1]  # Second positional argument
        
        # Verify is_related_query is True
        assert request_data["params"]["is_related_query"] is True
        assert request_data["params"]["frontend_context_uuid"] == "frontend-uuid"

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_reuses_context_uuid(self, mock_client_class):
        """Test that submit_followup_query reuses frontend_context_uuid."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        mock_client.stream_post.return_value = iter([])
        
        api = PerplexityAPI(token="test-token")
        thread_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="reused-uuid",
            context_uuid="context-uuid",
        )
        
        list(api.submit_followup_query("test query", thread_context))
        
        call_args = mock_client.stream_post.call_args
        request_data = call_args[0][1]
        
        # Verify frontend_context_uuid is reused
        assert request_data["params"]["frontend_context_uuid"] == "reused-uuid"
        # Verify new frontend_uuid is generated (different from context UUID)
        assert request_data["params"]["frontend_uuid"] != "reused-uuid"

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_includes_context_fields(self, mock_client_class):
        """Test that submit_followup_query includes context_uuid and read_write_token."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        mock_client.stream_post.return_value = iter([])
        
        api = PerplexityAPI(token="test-token")
        thread_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="backend-context-uuid",
            read_write_token="read-write-token-123",
        )
        
        list(api.submit_followup_query("test query", thread_context))
        
        call_args = mock_client.stream_post.call_args
        request_data = call_args[0][1]
        params = request_data["params"]
        
        # Verify all context fields are included
        assert params["frontend_context_uuid"] == "frontend-uuid"
        assert params["context_uuid"] == "backend-context-uuid"
        assert params["read_write_token"] == "read-write-token-123"
        assert params["is_related_query"] is True

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_submit_followup_query_handles_missing_token(self, mock_client_class):
        """Test that submit_followup_query handles missing read_write_token gracefully."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        mock_client.stream_post.return_value = iter([])
        
        api = PerplexityAPI(token="test-token")
        thread_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="backend-context-uuid",
            read_write_token=None,  # No token
        )
        
        list(api.submit_followup_query("test query", thread_context))
        
        call_args = mock_client.stream_post.call_args
        request_data = call_args[0][1]
        params = request_data["params"]
        
        # Verify context_uuid is included but read_write_token is not
        assert params["frontend_context_uuid"] == "frontend-uuid"
        assert params["context_uuid"] == "backend-context-uuid"
        assert "read_write_token" not in params  # Should not be included if None


class TestThreadContextStorage:
    """Test thread context storage functionality."""

    def test_save_and_load_thread_context(self, tmp_path, monkeypatch):
        """Test saving and loading thread context."""
        # Mock config directory to use temp path
        from perplexity_cli import utils
        
        def mock_get_config_dir():
            return tmp_path
        
        monkeypatch.setattr(utils.config, "get_config_dir", mock_get_config_dir)
        
        thread_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="context-uuid",
            read_write_token="token-123",
        )
        
        # Save context
        save_thread_context("test-slug", thread_context)
        
        # Load context
        loaded = load_thread_context("test-slug")
        assert loaded is not None
        assert loaded.thread_url_slug == "test-slug"
        assert loaded.frontend_context_uuid == "frontend-uuid"
        assert loaded.context_uuid == "context-uuid"
        assert loaded.read_write_token == "token-123"

    def test_load_nonexistent_thread_context(self, tmp_path, monkeypatch):
        """Test loading non-existent thread context."""
        from perplexity_cli import utils
        
        def mock_get_config_dir():
            return tmp_path
        
        monkeypatch.setattr(utils.config, "get_config_dir", mock_get_config_dir)
        
        loaded = load_thread_context("nonexistent-slug")
        assert loaded is None

    def test_clear_thread_context(self, tmp_path, monkeypatch):
        """Test clearing thread context."""
        from perplexity_cli import utils
        
        def mock_get_config_dir():
            return tmp_path
        
        monkeypatch.setattr(utils.config, "get_config_dir", mock_get_config_dir)
        
        thread_context = ThreadContext(
            thread_url_slug="test-slug",
            frontend_context_uuid="frontend-uuid",
            context_uuid="context-uuid",
        )
        
        # Save and then clear
        save_thread_context("test-slug", thread_context)
        clear_thread_context("test-slug")
        
        # Verify it's gone
        loaded = load_thread_context("test-slug")
        assert loaded is None

    def test_clear_all_thread_contexts(self, tmp_path, monkeypatch):
        """Test clearing all thread contexts."""
        from perplexity_cli import utils
        
        def mock_get_config_dir():
            return tmp_path
        
        monkeypatch.setattr(utils.config, "get_config_dir", mock_get_config_dir)
        
        # Save multiple contexts
        context1 = ThreadContext(
            thread_url_slug="slug-1",
            frontend_context_uuid="uuid-1",
            context_uuid="ctx-1",
        )
        context2 = ThreadContext(
            thread_url_slug="slug-2",
            frontend_context_uuid="uuid-2",
            context_uuid="ctx-2",
        )
        
        save_thread_context("slug-1", context1)
        save_thread_context("slug-2", context2)
        
        # Clear all
        clear_thread_context()
        
        # Verify both are gone
        assert load_thread_context("slug-1") is None
        assert load_thread_context("slug-2") is None

