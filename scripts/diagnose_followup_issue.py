#!/usr/bin/env python3
"""Diagnostic script to identify follow-up thread linking issues.

This script:
1. Submits an initial query
2. Sends a follow-up query
3. Checks if threads are linked correctly
4. Reports findings
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager


def diagnose_followup_issue():
    """Diagnose follow-up thread linking issue."""
    print("=" * 70)
    print("FOLLOW-UP DIAGNOSTIC")
    print("=" * 70)
    
    tm = TokenManager()
    token = tm.load_token()
    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        return
    
    api = PerplexityAPI(token=token)
    
    # Step 1: Submit initial query
    print("\n[Step 1] Submitting initial query...")
    initial_query = "What is machine learning?"
    initial_messages = []
    initial_context = None
    
    for message in api.submit_query(initial_query, auto_save_context=False):
        initial_messages.append(message)
        if message.final_sse_message:
            initial_context = api.extract_thread_context(initial_messages)
    
    if not initial_context:
        print("✗ Failed to extract context from initial query")
        return
    
    print(f"✓ Initial query completed")
    print(f"  Thread slug: {initial_context.thread_url_slug}")
    print(f"  Frontend context UUID: {initial_context.frontend_context_uuid}")
    print(f"  Context UUID: {initial_context.context_uuid}")
    print(f"  Read-write token: {initial_context.read_write_token[:20]}..." if initial_context.read_write_token else "  Read-write token: None")
    
    # Step 2: Submit follow-up query
    print("\n[Step 2] Submitting follow-up query...")
    followup_query = "What are its main applications?"
    followup_messages = []
    followup_context = None
    
    for message in api.submit_followup_query(followup_query, initial_context, auto_save_context=False):
        followup_messages.append(message)
        if message.final_sse_message:
            followup_context = api.extract_thread_context(followup_messages)
    
    if not followup_context:
        print("✗ Failed to extract context from follow-up query")
        return
    
    print(f"✓ Follow-up query completed")
    print(f"  Thread slug: {followup_context.thread_url_slug}")
    print(f"  Frontend context UUID: {followup_context.frontend_context_uuid}")
    print(f"  Context UUID: {followup_context.context_uuid}")
    
    # Step 3: Verify linking
    print("\n[Step 3] Verifying thread linking...")
    
    frontend_uuid_match = initial_context.frontend_context_uuid == followup_context.frontend_context_uuid
    print(f"  Frontend context UUID matches: {'✓' if frontend_uuid_match else '✗'}")
    if not frontend_uuid_match:
        print(f"    Initial:  {initial_context.frontend_context_uuid}")
        print(f"    Follow-up: {followup_context.frontend_context_uuid}")
    
    thread_slug_different = initial_context.thread_url_slug != followup_context.thread_url_slug
    print(f"  Thread slugs are different (expected): {'✓' if thread_slug_different else '✗'}")
    if not thread_slug_different:
        print(f"    Both: {initial_context.thread_url_slug}")
    
    # Step 4: Check thread list
    print("\n[Step 4] Checking thread list...")
    time.sleep(2)  # Give API time to update
    
    all_threads = api.list_threads(limit=100, offset=0, search_term="")
    
    # Find threads with same frontend_context_uuid
    matching_threads = [
        t for t in all_threads 
        if t.frontend_context_uuid == initial_context.frontend_context_uuid
    ]
    
    print(f"  Found {len(matching_threads)} thread(s) with matching frontend_context_uuid")
    
    if len(matching_threads) >= 2:
        print("  ✓ Threads are linked correctly!")
        print("\n  Linked threads:")
        for i, thread in enumerate(matching_threads[:5], 1):
            print(f"    {i}. {thread.slug[:50]}...")
            print(f"       Title: {thread.title}")
            print(f"       Last query: {thread.last_query_datetime}")
    else:
        print("  ✗ Threads are NOT linked correctly")
        print(f"  Expected at least 2 threads, found {len(matching_threads)}")
    
    # Step 5: Compare context sources
    print("\n[Step 5] Comparing context sources...")
    
    # Get context from list_threads()
    found_thread = None
    for thread in all_threads:
        if thread.slug == initial_context.thread_url_slug:
            found_thread = thread
            break
    
    if found_thread:
        list_context = found_thread.to_thread_context()
        print("  Context from list_threads():")
        print(f"    Frontend context UUID: {list_context.frontend_context_uuid}")
        print(f"    Context UUID: {list_context.context_uuid}")
        print(f"    Read-write token: {list_context.read_write_token[:20]}..." if list_context.read_write_token else "    Read-write token: None")
        print(f"    Thread URL slug: {list_context.thread_url_slug}")
        
        print("\n  Context from query response:")
        print(f"    Frontend context UUID: {initial_context.frontend_context_uuid}")
        print(f"    Context UUID: {initial_context.context_uuid}")
        print(f"    Read-write token: {initial_context.read_write_token[:20]}..." if initial_context.read_write_token else "    Read-write token: None")
        print(f"    Thread URL slug: {initial_context.thread_url_slug}")
        
        # Compare
        contexts_match = (
            list_context.frontend_context_uuid == initial_context.frontend_context_uuid and
            list_context.context_uuid == initial_context.context_uuid and
            list_context.read_write_token == initial_context.read_write_token
        )
        
        print(f"\n  Contexts match: {'✓' if contexts_match else '✗'}")
        if not contexts_match:
            print("  ⚠️  Context from list_threads() may be stale or incomplete")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if frontend_uuid_match and len(matching_threads) >= 2:
        print("✓ Follow-ups are working correctly!")
        print("  Threads are linked by frontend_context_uuid")
    else:
        print("✗ Follow-ups are NOT working correctly")
        if not frontend_uuid_match:
            print("  Issue: frontend_context_uuid doesn't match")
        if len(matching_threads) < 2:
            print(f"  Issue: Only {len(matching_threads)} thread(s) found (expected at least 2)")
    
    print("\nRecommendations:")
    if not frontend_uuid_match:
        print("  - Check that follow-up request includes correct frontend_context_uuid")
    if len(matching_threads) < 2:
        print("  - Check that follow-up request includes all required context fields")
        print("  - Verify is_related_query is set to true")
    if found_thread and not contexts_match:
        print("  - Consider using context from query response instead of list_threads()")


if __name__ == "__main__":
    diagnose_followup_issue()

