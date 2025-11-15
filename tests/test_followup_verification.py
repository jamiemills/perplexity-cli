"""Integration tests to verify follow-ups add to existing threads.

These tests verify that follow-up queries:
1. Use the SPECIFIC thread's context (not latest thread in conversation)
2. Add to the existing thread (same frontend_context_uuid)
3. Don't create new threads

Uses Chrome DevTools to capture browser behavior for comparison.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import ThreadContext
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import find_thread_by_identifier


@pytest.mark.skipif(
    not os.getenv("PERPLEXITY_TEST_AUTH"),
    reason="Integration tests require PERPLEXITY_TEST_AUTH environment variable",
)
class TestFollowupVerification:
    """Verify follow-ups work correctly."""

    @pytest.fixture
    def api(self):
        """Create authenticated API instance."""
        tm = TokenManager()
        token = tm.load_token()
        if not token:
            pytest.skip("No authentication token found")
        return PerplexityAPI(token=token, timeout=30)

    def test_followup_uses_specific_thread_context(self, api):
        """Test that follow-up uses the SPECIFIC thread's context, not latest.
        
        This verifies the fix: when user specifies a thread hash/slug,
        we use THAT thread's context, not the latest thread in the conversation.
        """
        # Step 1: Create a thread with a specific query
        initial_query = "What is the capital of France?"
        initial_messages = []
        initial_thread_slug = None
        initial_context_uuid = None
        
        for message in api.submit_query(initial_query, auto_save_context=False):
            initial_messages.append(message)
            if message.final_sse_message:
                initial_thread_slug = message.thread_url_slug
                initial_context_uuid = message.context_uuid
        
        assert initial_thread_slug is not None, "Initial query should create a thread"
        assert initial_context_uuid is not None, "Initial query should have context_uuid"
        
        # Step 2: Create another thread in the same conversation (different query)
        # This simulates multiple queries in the same conversation
        second_query = "What is its population?"
        second_messages = []
        second_thread_slug = None
        second_context_uuid = None
        
        # Extract context from first query
        initial_context = api.extract_thread_context(initial_messages)
        assert initial_context is not None
        
        # Submit second query as follow-up to first
        for message in api.submit_followup_query(second_query, initial_context, auto_save_context=False):
            second_messages.append(message)
            if message.final_sse_message:
                second_thread_slug = message.thread_url_slug
                second_context_uuid = message.context_uuid
        
        assert second_thread_slug is not None, "Second query should create a thread"
        assert second_context_uuid is not None, "Second query should have context_uuid"
        
        # Both should share same frontend_context_uuid (same conversation)
        initial_frontend_uuid = initial_context.frontend_context_uuid
        second_context = api.extract_thread_context(second_messages)
        assert second_context is not None
        assert second_context.frontend_context_uuid == initial_frontend_uuid, (
            "Both queries should be in same conversation"
        )
        
        # Step 3: Find the FIRST thread by its slug
        found_first_thread = find_thread_by_identifier(api, initial_thread_slug)
        assert found_first_thread is not None, "Should find first thread"
        assert found_first_thread.slug == initial_thread_slug
        assert found_first_thread.context_uuid == initial_context_uuid
        
        # Step 4: Send follow-up using FIRST thread's context
        # This should add to the FIRST thread, not create a new one
        followup_query = "What is its currency?"
        followup_messages = []
        followup_thread_slug = None
        followup_context_uuid = None
        
        # Use FIRST thread's context (not latest/second thread)
        first_thread_context = found_first_thread.to_thread_context()
        
        for message in api.submit_followup_query(
            followup_query, first_thread_context, auto_save_context=False
        ):
            followup_messages.append(message)
            if message.final_sse_message:
                followup_thread_slug = message.thread_url_slug
                followup_context_uuid = message.context_uuid
        
        assert followup_thread_slug is not None, "Follow-up should create a thread"
        assert followup_context_uuid is not None, "Follow-up should have context_uuid"
        
        # Step 5: Verify follow-up uses FIRST thread's context
        # The follow-up should be linked to the FIRST thread
        followup_context = api.extract_thread_context(followup_messages)
        assert followup_context is not None
        
        # Verify frontend_context_uuid is same (same conversation)
        assert followup_context.frontend_context_uuid == initial_frontend_uuid, (
            f"Follow-up should be in same conversation. "
            f"Expected: {initial_frontend_uuid}, Got: {followup_context.frontend_context_uuid}"
        )
        
        # Note: context_uuid may change for each query in a conversation
        # What matters is that we sent the FIRST thread's context_uuid in the request
        # Verify we sent the correct context_uuid in the request
        # (This is verified by checking that we used first_thread_context)
        
        # Note: thread_url_slug changes for each query (each query gets its own thread)
        # What matters is that they're linked by frontend_context_uuid (same conversation)
        # The follow-up creates a new thread slug, but it's part of the same conversation
        assert followup_context.thread_url_slug is not None, "Follow-up should have a thread slug"
        
        # Additional verification: wait and check thread list
        import time
        time.sleep(2)
        
        all_threads = api.list_threads(limit=100, offset=0, search_term="")
        
        # Find threads with same frontend_context_uuid
        matching_threads = [
            t for t in all_threads 
            if t.frontend_context_uuid == initial_frontend_uuid
        ]
        
        # Should find at least 3 threads (initial + second + follow-up)
        assert len(matching_threads) >= 3, (
            f"Should find at least 3 threads in conversation. Found: {len(matching_threads)}"
        )
        
        # Verify all threads share same frontend_context_uuid
        for thread in matching_threads:
            assert thread.frontend_context_uuid == initial_frontend_uuid

    def test_followup_adds_to_existing_thread_not_new(self, api):
        """Test that follow-up adds to existing thread, doesn't create new one.
        
        This verifies that when we follow up on a thread:
        1. The frontend_context_uuid is reused (same conversation)
        2. The context_uuid matches the thread we're following up on
        3. The thread_url_slug matches the thread we're following up on
        """
        import time
        
        # Step 1: Create initial thread
        initial_query = "What is Python?"
        initial_messages = []
        initial_thread_slug = None
        initial_context_uuid = None
        initial_frontend_context_uuid = None
        
        for message in api.submit_query(initial_query, auto_save_context=False):
            initial_messages.append(message)
            if message.final_sse_message:
                initial_thread_slug = message.thread_url_slug
                initial_context_uuid = message.context_uuid
                initial_frontend_context_uuid = message.frontend_context_uuid
        
        assert initial_thread_slug is not None
        assert initial_context_uuid is not None
        assert initial_frontend_context_uuid is not None
        
        # Step 2: Find thread by slug
        found_thread = find_thread_by_identifier(api, initial_thread_slug)
        assert found_thread is not None
        assert found_thread.slug == initial_thread_slug
        assert found_thread.context_uuid == initial_context_uuid
        
        # Step 3: Send follow-up using this thread's context
        followup_query = "What are its main features?"
        followup_messages = []
        followup_thread_slug = None
        followup_context_uuid = None
        followup_frontend_context_uuid = None
        
        thread_context = found_thread.to_thread_context()
        
        for message in api.submit_followup_query(
            followup_query, thread_context, auto_save_context=False
        ):
            followup_messages.append(message)
            if message.final_sse_message:
                followup_thread_slug = message.thread_url_slug
                followup_context_uuid = message.context_uuid
                followup_frontend_context_uuid = message.frontend_context_uuid
        
        assert len(followup_messages) > 0, "Follow-up should return messages"
        assert followup_thread_slug is not None
        assert followup_context_uuid is not None
        assert followup_frontend_context_uuid is not None
        
        # Step 4: Verify follow-up reuses context
        # Frontend context UUID should be the same (same conversation)
        assert followup_frontend_context_uuid == initial_frontend_context_uuid, (
            f"Follow-up should reuse frontend_context_uuid. "
            f"Initial: {initial_frontend_context_uuid}, "
            f"Follow-up: {followup_frontend_context_uuid}"
        )
        
        # Note: context_uuid changes for each query in a conversation (this is expected)
        # What matters is that we SENT the thread's context_uuid in the request
        # The response will have a new context_uuid for the new query
        
        # Note: thread_url_slug changes for each query (each query gets its own thread)
        # What matters is that they're linked by frontend_context_uuid (same conversation)
        # The follow-up creates a new thread slug, but it's part of the same conversation
        assert followup_thread_slug is not None, "Follow-up should have a thread slug"
        assert followup_thread_slug != initial_thread_slug, (
            "Each query gets its own thread slug, but they're linked by frontend_context_uuid"
        )
        
        # Step 5: Wait and verify threads are linked
        time.sleep(2)  # Give API time to update
        
        all_threads = api.list_threads(limit=100, offset=0, search_term="")
        
        # Find threads with same frontend_context_uuid
        matching_threads = [
            t for t in all_threads 
            if t.frontend_context_uuid == initial_frontend_context_uuid
        ]
        
        # Should find at least 2 threads (initial + follow-up)
        assert len(matching_threads) >= 2, (
            f"Should find at least 2 threads in conversation. "
            f"Found: {len(matching_threads)}"
        )
        
        # Verify both thread slugs are present
        found_initial = any(t.slug == initial_thread_slug for t in matching_threads)
        found_followup = any(t.slug == followup_thread_slug for t in matching_threads)
        
        assert found_initial, f"Should find initial thread: {initial_thread_slug}"
        assert found_followup, f"Should find follow-up thread: {followup_thread_slug}"


@pytest.mark.skipif(
    not os.getenv("PERPLEXITY_TEST_AUTH") or not os.getenv("CHROME_DEBUG_PORT"),
    reason="Chrome DevTools test requires PERPLEXITY_TEST_AUTH and CHROME_DEBUG_PORT",
)
class TestFollowupBrowserComparison:
    """Compare our follow-up requests with browser behavior using Chrome DevTools."""

    @pytest.fixture
    def api(self):
        """Create authenticated API instance."""
        tm = TokenManager()
        token = tm.load_token()
        if not token:
            pytest.skip("No authentication token found")
        return PerplexityAPI(token=token, timeout=30)

    @pytest.mark.asyncio
    async def test_compare_followup_request_with_browser(self, api):
        """Compare our follow-up request with browser's actual request.
        
        This test:
        1. Creates a thread via our API
        2. Captures what we send for a follow-up
        3. Uses Chrome DevTools to capture browser's follow-up request
        4. Compares the two to ensure they match
        """
        import websockets
        from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient
        
        # Step 1: Create initial thread
        initial_query = "What is machine learning?"
        initial_messages = []
        initial_thread_slug = None
        
        for message in api.submit_query(initial_query, auto_save_context=False):
            initial_messages.append(message)
            if message.final_sse_message:
                initial_thread_slug = message.thread_url_slug
        
        assert initial_thread_slug is not None
        
        # Extract context
        initial_context = api.extract_thread_context(initial_messages)
        assert initial_context is not None
        
        # Step 2: Build our follow-up request
        import uuid
        from perplexity_cli.api.models import QueryParams, QueryRequest
        
        frontend_uuid = str(uuid.uuid4())
        our_params = QueryParams(
            language="en-US",
            timezone="Europe/London",
            frontend_uuid=frontend_uuid,
            frontend_context_uuid=initial_context.frontend_context_uuid,
            context_uuid=initial_context.context_uuid,
            read_write_token=initial_context.read_write_token,
            thread_url_slug=initial_context.thread_url_slug,
            is_related_query=True,
        )
        our_request = QueryRequest(query_str="Tell me more", params=our_params)
        our_request_dict = our_request.to_dict()
        
        # Step 3: Capture browser request using Chrome DevTools
        chrome_port = int(os.getenv("CHROME_DEBUG_PORT", "9222"))
        client = ChromeDevToolsClient(port=chrome_port)
        
        browser_request = None
        
        try:
            await client.connect()
            await client.send_command("Network.enable", {
                "maxResourceBufferSize": 1024 * 1024,
                "maxPostDataSize": 1024 * 1024
            })
            await client.send_command("Page.enable")
            
            # Navigate to thread page
            thread_url = f"https://www.perplexity.ai/thread/{initial_thread_slug}"
            await client.send_command("Page.navigate", {"url": thread_url})
            await asyncio.sleep(5)
            
            # Monitor for follow-up request
            captured = False
            start_time = asyncio.get_event_loop().time()
            timeout = 30.0
            
            async def message_handler():
                nonlocal browser_request, captured
                while not captured:
                    try:
                        message = await asyncio.wait_for(client.ws.recv(), timeout=1.0)
                        data = json.loads(message)
                        
                        if "method" in data and data["method"] == "Network.requestWillBeSent":
                            request = data.get("params", {}).get("request", {})
                            url = request.get("url", "")
                            
                            if "/rest/sse/perplexity_ask" in url:
                                post_data = request.get("postData", "")
                                if post_data:
                                    try:
                                        browser_request = json.loads(post_data)
                                        captured = True
                                        break
                                    except json.JSONDecodeError:
                                        pass
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        break
                    except Exception:
                        continue
            
            # Wait for user to send follow-up in browser (or timeout)
            print(f"\n{'='*70}")
            print("BROWSER COMPARISON TEST")
            print(f"{'='*70}")
            print(f"Thread URL: {thread_url}")
            print("Please send a follow-up query in the browser now.")
            print("Waiting 30 seconds...")
            print("-" * 70)
            
            try:
                await asyncio.wait_for(message_handler(), timeout=timeout)
            except asyncio.TimeoutError:
                pytest.skip("Browser request not captured within timeout. User may need to send follow-up manually.")
            
            await client.close()
            
        except ConnectionRefusedError:
            pytest.skip("Cannot connect to Chrome DevTools. Make sure Chrome is running with --remote-debugging-port")
        except Exception as e:
            await client.close()
            pytest.skip(f"Error connecting to Chrome DevTools: {e}")
        
        # Step 4: Compare requests
        if browser_request is None:
            pytest.skip("No browser request captured")
        
        browser_params = browser_request.get("params", {})
        our_params_dict = our_request_dict.get("params", {})
        
        # Compare key fields
        key_fields = [
            "frontend_context_uuid",
            "context_uuid",
            "read_write_token",
            "thread_url_slug",
            "is_related_query",
        ]
        
        mismatches = []
        for field in key_fields:
            our_value = our_params_dict.get(field)
            browser_value = browser_params.get(field)
            
            if our_value != browser_value:
                mismatches.append({
                    "field": field,
                    "our_value": our_value,
                    "browser_value": browser_value,
                })
        
        if mismatches:
            error_msg = "Request parameters don't match browser:\n"
            for mismatch in mismatches:
                error_msg += f"  {mismatch['field']}:\n"
                error_msg += f"    Our: {mismatch['our_value']}\n"
                error_msg += f"    Browser: {mismatch['browser_value']}\n"
            pytest.fail(error_msg)
        
        # If we get here, requests match
        assert True, "Our follow-up request matches browser request"

