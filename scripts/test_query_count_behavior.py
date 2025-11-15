#!/usr/bin/env python3
"""Test query_count behavior when following up on a thread.

This script:
1. Creates an initial query
2. Follows up on it
3. Checks if query_count increments for the original thread
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager


def test_query_count():
    """Test query_count behavior."""
    tm = TokenManager()
    token = tm.load_token()
    if not token:
        print("✗ Not authenticated. Run: perplexity-cli auth")
        return
    
    api = PerplexityAPI(token=token)
    
    print("=" * 70)
    print("TESTING QUERY COUNT BEHAVIOR")
    print("=" * 70)
    
    # Step 1: Create initial query
    print("\n1. Creating initial query...")
    initial_query = "What is Python?"
    initial_messages = []
    initial_thread_slug = None
    initial_context_uuid = None
    
    for message in api.submit_query(initial_query, auto_save_context=False):
        initial_messages.append(message)
        if message.final_sse_message:
            initial_thread_slug = message.thread_url_slug
            initial_context_uuid = message.context_uuid
    
    print(f"   ✓ Initial thread slug: {initial_thread_slug}")
    print(f"   ✓ Initial context_uuid: {initial_context_uuid}")
    
    # Step 2: Get initial thread info
    print("\n2. Getting initial thread info...")
    import time
    time.sleep(2)  # Wait for API to update
    
    all_threads = api.list_threads(limit=100, offset=0, search_term="")
    initial_thread = None
    for t in all_threads:
        if t.slug == initial_thread_slug:
            initial_thread = t
            break
    
    if not initial_thread:
        print("   ✗ Could not find initial thread")
        return
    
    print(f"   ✓ Initial thread query_count: {initial_thread.query_count}")
    print(f"   ✓ Initial thread total_threads: {initial_thread.total_threads}")
    print(f"   ✓ Initial thread frontend_context_uuid: {initial_thread.frontend_context_uuid}")
    
    # Step 3: Follow up on the thread
    print("\n3. Following up on thread...")
    initial_context = api.extract_thread_context(initial_messages)
    assert initial_context is not None
    
    followup_query = "What are its main features?"
    followup_messages = []
    followup_thread_slug = None
    
    for message in api.submit_followup_query(followup_query, initial_context, auto_save_context=False):
        followup_messages.append(message)
        if message.final_sse_message:
            followup_thread_slug = message.thread_url_slug
    
    print(f"   ✓ Follow-up thread slug: {followup_thread_slug}")
    
    # Step 4: Check thread info after follow-up
    print("\n4. Checking thread info after follow-up...")
    time.sleep(2)  # Wait for API to update
    
    all_threads_after = api.list_threads(limit=100, offset=0, search_term="")
    
    # Find original thread
    original_thread_after = None
    followup_thread_after = None
    
    for t in all_threads_after:
        if t.slug == initial_thread_slug:
            original_thread_after = t
        if t.slug == followup_thread_slug:
            followup_thread_after = t
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    if original_thread_after:
        print(f"\nOriginal thread ({initial_thread_slug}):")
        print(f"  query_count: {initial_thread.query_count} → {original_thread_after.query_count}")
        print(f"  total_threads: {initial_thread.total_threads} → {original_thread_after.total_threads}")
        print(f"  frontend_context_uuid: {original_thread_after.frontend_context_uuid}")
    else:
        print(f"\n✗ Original thread not found after follow-up")
    
    if followup_thread_after:
        print(f"\nFollow-up thread ({followup_thread_slug}):")
        print(f"  query_count: {followup_thread_after.query_count}")
        print(f"  total_threads: {followup_thread_after.total_threads}")
        print(f"  frontend_context_uuid: {followup_thread_after.frontend_context_uuid}")
    
    # Check if they share same frontend_context_uuid
    if original_thread_after and followup_thread_after:
        if original_thread_after.frontend_context_uuid == followup_thread_after.frontend_context_uuid:
            print(f"\n✓ Both threads share same frontend_context_uuid (same conversation)")
        else:
            print(f"\n✗ Threads have different frontend_context_uuid")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print("\nBased on this test:")
    if original_thread_after:
        if original_thread_after.query_count > initial_thread.query_count:
            print("✓ query_count DOES increment for the original thread")
        else:
            print("✗ query_count does NOT increment for the original thread")
            print("  (Each query creates a new thread slug with query_count=1)")
        
        if original_thread_after.total_threads > initial_thread.total_threads:
            print("✓ total_threads DOES increment (shows total queries in conversation)")
        else:
            print("✗ total_threads does NOT increment")


if __name__ == "__main__":
    test_query_count()

