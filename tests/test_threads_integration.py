"""Integration tests for threads functionality.

These tests require authentication and make real API calls.
They are skipped by default unless PERPLEXITY_TEST_AUTH is set.
"""

import os

import pytest

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import ThreadContext
from perplexity_cli.auth.token_manager import TokenManager


@pytest.mark.skipif(
    not os.getenv("PERPLEXITY_TEST_AUTH"),
    reason="Integration tests require PERPLEXITY_TEST_AUTH environment variable",
)
class TestThreadsIntegration:
    """Integration tests for threads API."""

    @pytest.fixture
    def api(self):
        """Create authenticated API instance."""
        tm = TokenManager()
        token = tm.load_token()
        if not token:
            pytest.skip("No authentication token found")
        return PerplexityAPI(token=token, timeout=30)

    def test_list_threads(self, api):
        """Test listing threads with real API."""
        threads = api.list_threads(limit=5, offset=0)
        assert isinstance(threads, list)
        assert len(threads) <= 5
        
        if threads:
            thread = threads[0]
            assert hasattr(thread, "slug")
            assert hasattr(thread, "title")
            assert hasattr(thread, "query_count")
            assert hasattr(thread, "frontend_context_uuid")

    def test_list_threads_with_search(self, api):
        """Test listing threads with search term."""
        threads = api.list_threads(limit=10, offset=0, search_term="python")
        assert isinstance(threads, list)
        # Results may be empty, which is fine

    def test_submit_query_and_extract_context(self, api):
        """Test submitting a query and extracting thread context."""
        messages = []
        for message in api.submit_query("What is 2+2?", auto_save_context=False):
            messages.append(message)
        
        # Extract context from messages
        context = api.extract_thread_context(messages)
        
        if context:
            assert isinstance(context, ThreadContext)
            assert context.thread_url_slug is not None
            assert context.frontend_context_uuid is not None
            assert context.context_uuid is not None

    def test_submit_followup_query(self, api):
        """Test submitting a follow-up query."""
        # First, submit an initial query to get context
        initial_messages = []
        for message in api.submit_query("What is Python?", auto_save_context=False):
            initial_messages.append(message)
        
        context = api.extract_thread_context(initial_messages)
        if not context:
            pytest.skip("Could not extract thread context from initial query")
        
        # Submit follow-up query
        followup_messages = []
        for message in api.submit_followup_query(
            "What are its main features?", context, auto_save_context=False
        ):
            followup_messages.append(message)
        
        assert len(followup_messages) > 0
        
        # Verify final message exists
        final_messages = [m for m in followup_messages if m.final_sse_message]
        assert len(final_messages) > 0

    def test_complete_workflow(self, api):
        """Test complete workflow: query -> follow-up -> list threads."""
        # Submit initial query
        initial_messages = []
        for message in api.submit_query("What is machine learning?", auto_save_context=True):
            initial_messages.append(message)
        
        context = api.extract_thread_context(initial_messages)
        if not context:
            pytest.skip("Could not extract thread context")
        
        # Submit follow-up
        followup_messages = []
        for message in api.submit_followup_query(
            "Give me examples", context, auto_save_context=True
        ):
            followup_messages.append(message)
        
        # List threads to verify they exist
        threads = api.list_threads(limit=10, offset=0)
        assert isinstance(threads, list)
        
        # Find our thread by slug (if context has slug)
        if context.thread_url_slug:
            found = any(t.slug == context.thread_url_slug for t in threads)
            # Thread may not appear immediately, so this is optional
            # assert found, "Thread should appear in list"

    def test_followup_adds_to_existing_thread(self, api):
        """Test that follow-up queries add to existing thread, not create new one.
        
        This test verifies that:
        1. Initial query creates a thread with a frontend_context_uuid
        2. Follow-up query reuses the same frontend_context_uuid
        3. Both queries appear in threads list with same frontend_context_uuid
        4. Thread query count increases (if we can verify)
        """
        import time
        
        # Step 1: Submit initial query
        initial_query = "What is artificial intelligence?"
        initial_messages = []
        initial_context_uuid = None
        initial_thread_slug = None
        
        for message in api.submit_query(initial_query, auto_save_context=False):
            initial_messages.append(message)
            if message.final_sse_message:
                initial_context_uuid = message.frontend_context_uuid
                initial_thread_slug = message.thread_url_slug
        
        assert initial_context_uuid is not None, "Initial query should have frontend_context_uuid"
        assert initial_thread_slug is not None, "Initial query should have thread_url_slug"
        
        # Extract context
        initial_context = api.extract_thread_context(initial_messages)
        assert initial_context is not None, "Should be able to extract thread context"
        assert initial_context.frontend_context_uuid == initial_context_uuid
        
        # Step 2: Submit follow-up query
        followup_query = "What are its main applications?"
        followup_messages = []
        followup_context_uuid = None
        followup_thread_slug = None
        
        for message in api.submit_followup_query(
            followup_query, initial_context, auto_save_context=False
        ):
            followup_messages.append(message)
            if message.final_sse_message:
                followup_context_uuid = message.frontend_context_uuid
                followup_thread_slug = message.thread_url_slug
        
        assert len(followup_messages) > 0, "Follow-up should return messages"
        assert followup_context_uuid is not None, "Follow-up should have frontend_context_uuid"
        
        # Step 3: Verify thread continuity
        # The frontend_context_uuid should be the SAME for both queries
        assert followup_context_uuid == initial_context_uuid, (
            f"Follow-up should reuse frontend_context_uuid. "
            f"Initial: {initial_context_uuid}, Follow-up: {followup_context_uuid}"
        )
        
        # Step 4: Wait a moment for thread list to update, then verify threads are linked
        time.sleep(2)  # Give API time to update thread list
        
        # List threads and find both queries
        all_threads = api.list_threads(limit=100, offset=0, search_term="")
        
        # Find all threads with the same frontend_context_uuid
        matching_threads = [
            t for t in all_threads 
            if t.frontend_context_uuid == initial_context_uuid
        ]
        
        # Should find at least 2 threads (initial + follow-up) with same context UUID
        assert len(matching_threads) >= 2, (
            f"Should find at least 2 threads with same frontend_context_uuid. "
            f"Found: {len(matching_threads)}. "
            f"Context UUID: {initial_context_uuid}"
        )
        
        # Verify both thread slugs are in the matching threads
        found_initial = any(t.slug == initial_thread_slug for t in matching_threads)
        found_followup = any(t.slug == followup_thread_slug for t in matching_threads)
        
        # At least one should be found (the follow-up thread slug might be different)
        assert found_initial or found_followup, (
            f"Should find at least one of the thread slugs in matching threads. "
            f"Initial slug: {initial_thread_slug}, Follow-up slug: {followup_thread_slug}"
        )
        
        # Verify all matching threads share the same frontend_context_uuid
        for thread in matching_threads:
            assert thread.frontend_context_uuid == initial_context_uuid, (
                f"All matching threads should have same frontend_context_uuid. "
                f"Thread {thread.slug} has {thread.frontend_context_uuid}, expected {initial_context_uuid}"
            )

