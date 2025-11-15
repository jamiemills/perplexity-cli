"""Test that follow-up queries properly link to existing threads.

This test verifies that follow-up queries add to existing threads instead of
creating new ones by checking that frontend_context_uuid is reused.
"""

import pytest
from unittest.mock import MagicMock, patch

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import SSEMessage, Thread, ThreadContext


class TestFollowupThreadLinking:
    """Test that follow-ups link to existing threads."""

    @patch("perplexity_cli.api.endpoints.SSEClient")
    def test_followup_reuses_frontend_context_uuid(self, mock_client_class):
        """Test that follow-up query reuses frontend_context_uuid from initial query."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        
        # Mock initial query response
        initial_frontend_context_uuid = "shared-context-uuid-123"
        initial_thread_slug = "initial-query-slug"
        
        initial_messages = [
            SSEMessage(
                backend_uuid="backend-1",
                context_uuid="context-1",
                uuid="uuid-1",
                frontend_context_uuid=initial_frontend_context_uuid,
                display_model="pplx_pro",
                mode="copilot",
                thread_url_slug=initial_thread_slug,
                status="completed",
                text_completed=True,
                blocks=[],
                final_sse_message=True,
                read_write_token="token-123",
            )
        ]
        
        # Mock follow-up query response - should have SAME frontend_context_uuid
        followup_thread_slug = "followup-query-slug"  # Slug changes, but context UUID stays same
        followup_messages = [
            SSEMessage(
                backend_uuid="backend-2",
                context_uuid="context-1",  # Same context_uuid
                uuid="uuid-2",
                frontend_context_uuid=initial_frontend_context_uuid,  # SAME frontend_context_uuid
                display_model="pplx_pro",
                mode="copilot",
                thread_url_slug=followup_thread_slug,
                status="completed",
                text_completed=True,
                blocks=[],
                final_sse_message=True,
                read_write_token="token-123",
            )
        ]
        
        # Convert SSEMessage objects to dict format (as API returns)
        def sse_message_to_dict(msg: SSEMessage) -> dict:
            """Convert SSEMessage to dict format as returned by API."""
            result = {
                "backend_uuid": msg.backend_uuid,
                "context_uuid": msg.context_uuid,
                "uuid": msg.uuid,
                "frontend_context_uuid": msg.frontend_context_uuid,
                "display_model": msg.display_model,
                "mode": msg.mode,
                "thread_url_slug": msg.thread_url_slug,
                "status": msg.status,
                "text_completed": msg.text_completed,
                "blocks": [],
                "final_sse_message": msg.final_sse_message,
            }
            if msg.cursor:
                result["cursor"] = msg.cursor
            if msg.read_write_token:
                result["read_write_token"] = msg.read_write_token
            return result
        
        # Set up mock to return different responses for initial vs follow-up
        call_count = 0
        def mock_stream_post(endpoint, data):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Initial query
                return iter([sse_message_to_dict(msg) for msg in initial_messages])
            else:
                # Follow-up query
                return iter([sse_message_to_dict(msg) for msg in followup_messages])
        
        mock_client.stream_post.side_effect = mock_stream_post
        
        api = PerplexityAPI(token="test-token")
        
        # Step 1: Submit initial query
        initial_context = None
        for message in api.submit_query("What is Python?", auto_save_context=False):
            if message.final_sse_message:
                initial_context = api.extract_thread_context([message])
                break
        
        assert initial_context is not None
        assert initial_context.frontend_context_uuid == initial_frontend_context_uuid
        
        # Step 2: Submit follow-up query
        followup_context_uuid = None
        for message in api.submit_followup_query(
            "What are its features?", initial_context, auto_save_context=False
        ):
            if message.final_sse_message:
                followup_context_uuid = message.frontend_context_uuid
                break
        
        # Step 3: Verify frontend_context_uuid is reused
        assert followup_context_uuid == initial_frontend_context_uuid, (
            f"Follow-up should reuse frontend_context_uuid. "
            f"Initial: {initial_frontend_context_uuid}, Follow-up: {followup_context_uuid}"
        )
        
        # Verify the request included the correct context
        assert mock_client.stream_post.call_count == 2
        
        # Check follow-up request parameters
        followup_call = mock_client.stream_post.call_args_list[1]
        followup_request = followup_call[0][1]  # Second positional arg
        followup_params = followup_request["params"]
        
        assert followup_params["frontend_context_uuid"] == initial_frontend_context_uuid
        assert followup_params["is_related_query"] is True

    @patch("perplexity_cli.api.endpoints.SSEClient")
    @patch("perplexity_cli.api.endpoints.PerplexityAPI.list_threads")
    def test_followup_uses_latest_thread_context(self, mock_list_threads, mock_client_class):
        """Test that follow-up uses latest thread context when multiple threads share same UUID."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_headers.return_value = {"Authorization": "Bearer test"}
        mock_client.timeout = 60
        
        shared_context_uuid = "shared-context-uuid-456"
        
        # Create mock threads - all share same frontend_context_uuid but different slugs
        # Thread 1: older query
        thread1 = Thread(
            thread_number=0,
            slug="older-query-slug",
            title="Older query",
            context_uuid="context-1",
            frontend_context_uuid=shared_context_uuid,
            read_write_token="token-123",
            first_answer='{"answer":"old answer"}',
            last_query_datetime="2025-01-01T10:00:00",
            query_count=1,
            total_threads=2,
            has_next_page=False,
            mode="copilot",
            uuid="uuid-1",
            frontend_uuid="frontend-1",
            thread_access=1,
            status="COMPLETED",
            first_entry_model_preference="PPLX_PRO",
            display_model="pplx_pro",
        )
        
        # Thread 2: newer query (latest)
        thread2 = Thread(
            thread_number=1,
            slug="newer-query-slug",
            title="Newer query",
            context_uuid="context-1",
            frontend_context_uuid=shared_context_uuid,
            read_write_token="token-456",  # Different token (more recent)
            first_answer='{"answer":"new answer"}',
            last_query_datetime="2025-01-01T12:00:00",  # Newer timestamp
            query_count=2,
            total_threads=2,
            has_next_page=False,
            mode="copilot",
            uuid="uuid-2",
            frontend_uuid="frontend-2",
            thread_access=1,
            status="COMPLETED",
            first_entry_model_preference="PPLX_PRO",
            display_model="pplx_pro",
        )
        
        # Mock list_threads to return both threads
        mock_list_threads.return_value = [thread1, thread2]
        
        # Mock follow-up response
        followup_response = SSEMessage(
            backend_uuid="backend-3",
            context_uuid="context-1",
            uuid="uuid-3",
            frontend_context_uuid=shared_context_uuid,  # Same context UUID
            display_model="pplx_pro",
            mode="copilot",
            thread_url_slug="followup-slug",
            status="completed",
            text_completed=True,
            blocks=[],
            final_sse_message=True,
            read_write_token="token-789",
        )
        
        # Convert SSEMessage to dict format
        followup_response_dict = {
            "backend_uuid": followup_response.backend_uuid,
            "context_uuid": followup_response.context_uuid,
            "uuid": followup_response.uuid,
            "frontend_context_uuid": followup_response.frontend_context_uuid,
            "display_model": followup_response.display_model,
            "mode": followup_response.mode,
            "thread_url_slug": followup_response.thread_url_slug,
            "status": followup_response.status,
            "text_completed": followup_response.text_completed,
            "blocks": [],
            "final_sse_message": followup_response.final_sse_message,
            "read_write_token": followup_response.read_write_token,
        }
        mock_client.stream_post.return_value = iter([followup_response_dict])
        
        api = PerplexityAPI(token="test-token")
        
        # Simulate looking up thread1 (older query) by hash/slug
        found_thread = thread1
        
        # When we do a follow-up, we should use thread2's context (latest)
        # This simulates what happens in the CLI when finding latest thread
        from datetime import datetime
        
        all_threads = api.list_threads(limit=100, offset=0)
        matching_threads = [
            t for t in all_threads 
            if t.frontend_context_uuid == found_thread.frontend_context_uuid
        ]
        
        # Sort by datetime to get latest
        def parse_datetime(dt_str: str) -> datetime:
            try:
                if dt_str.endswith("Z"):
                    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                return datetime.fromisoformat(dt_str)
            except (ValueError, AttributeError):
                return datetime.fromtimestamp(0)
        
        matching_threads.sort(
            key=lambda t: parse_datetime(t.last_query_datetime),
            reverse=True
        )
        latest_thread = matching_threads[0]
        
        # Verify we're using the latest thread (thread2)
        assert latest_thread.slug == "newer-query-slug"
        assert latest_thread.read_write_token == "token-456"
        
        # Use latest thread's context for follow-up
        thread_context = latest_thread.to_thread_context()
        
        # Submit follow-up
        for message in api.submit_followup_query(
            "Follow-up question", thread_context, auto_save_context=False
        ):
            if message.final_sse_message:
                assert message.frontend_context_uuid == shared_context_uuid
                break
        
        # Verify list_threads was called to find latest context
        assert mock_list_threads.called
        
        # Verify follow-up request used latest thread's context
        followup_call = mock_client.stream_post.call_args
        followup_request = followup_call[0][1]
        followup_params = followup_request["params"]
        
        assert followup_params["frontend_context_uuid"] == shared_context_uuid
        assert followup_params["read_write_token"] == "token-456"  # From latest thread
        assert followup_params["thread_url_slug"] == "newer-query-slug"  # From latest thread

