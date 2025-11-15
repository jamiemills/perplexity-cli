#!/usr/bin/env python3
"""Test follow-up query pattern with thread context.

This script tests sending a follow-up query to an existing thread by:
1. Sending an initial query and capturing thread context
2. Sending a follow-up query using the captured context
3. Comparing the responses to verify thread continuity

Run with: python scripts/test_followup_query.py
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import QueryParams, QueryRequest
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_query_endpoint
from perplexity_cli.utils.logging import setup_logging


def main():
    """Test follow-up query pattern."""
    setup_logging(verbose=True)

    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        sys.exit(1)

    print("=" * 70)
    print("Follow-up Query Pattern Test")
    print("=" * 70)
    print()

    api = PerplexityAPI(token=token)

    # Step 1: Initial query
    initial_query = "What is Python?"
    print(f"Step 1: Sending initial query: '{initial_query}'")
    print("-" * 70)

    thread_context = None
    initial_messages = []

    try:
        for message in api.submit_query(initial_query):
            initial_messages.append(message)
            if message.final_sse_message:
                # Extract thread context
                thread_context = {
                    "thread_url_slug": message.thread_url_slug,
                    "frontend_context_uuid": message.frontend_context_uuid,
                    "context_uuid": message.context_uuid,
                    "cursor": message.cursor,
                    "read_write_token": message.read_write_token,
                }
                print(f"\n✓ Initial query complete")
                print(f"  Thread URL slug: {thread_context['thread_url_slug']}")
                print(f"  Frontend context UUID: {thread_context['frontend_context_uuid']}")
                break
    except Exception as e:
        print(f"\n✗ Error in initial query: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if not thread_context or not thread_context["frontend_context_uuid"]:
        print("\n✗ Failed to extract thread context from initial query")
        sys.exit(1)

    # Step 2: Follow-up query
    followup_query = "What are its main features?"
    print(f"\nStep 2: Sending follow-up query: '{followup_query}'")
    print("-" * 70)
    print(f"  Using context UUID: {thread_context['frontend_context_uuid']}")
    print(f"  Thread slug: {thread_context['thread_url_slug']}")

    # Manually construct follow-up query with thread context
    import uuid
    from perplexity_cli.api.client import SSEClient

    client = SSEClient(token=token)
    query_endpoint = get_query_endpoint()

    # Build follow-up query parameters
    params = QueryParams(
        frontend_uuid=str(uuid.uuid4()),  # New UUID for this query
        frontend_context_uuid=thread_context["frontend_context_uuid"],  # Reuse context
        is_related_query=True,  # Mark as follow-up
    )

    request = QueryRequest(query_str=followup_query, params=params)
    followup_messages = []

    try:
        for message_data in client.stream_post(query_endpoint, request.to_dict()):
            from perplexity_cli.api.models import SSEMessage
            message = SSEMessage.from_dict(message_data)
            followup_messages.append(message)

            if message.final_sse_message:
                print(f"\n✓ Follow-up query complete")
                print(f"  Thread URL slug: {message.thread_url_slug}")
                print(f"  Frontend context UUID: {message.frontend_context_uuid}")
                break
    except Exception as e:
        print(f"\n✗ Error in follow-up query: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 3: Analysis
    print("\n" + "=" * 70)
    print("Analysis")
    print("=" * 70)

    # Check if thread context matches
    if followup_messages:
        last_message = followup_messages[-1]
        context_matches = (
            last_message.frontend_context_uuid == thread_context["frontend_context_uuid"]
        )
        slug_matches = (
            last_message.thread_url_slug == thread_context["thread_url_slug"]
        )

        print(f"\nThread Continuity Check:")
        print(f"  Context UUID matches: {context_matches}")
        print(f"  Thread slug matches: {slug_matches}")

        if context_matches and slug_matches:
            print("\n✓ Follow-up query successfully linked to thread!")
        elif context_matches:
            print("\n⚠ Context matches but thread slug differs (may be expected)")
        else:
            print("\n✗ Thread context does not match - follow-up may not be linked")

    # Save test results
    output_file = Path(__file__).parent.parent / "docs" / "followup_test_results.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({
            "initial_query": initial_query,
            "followup_query": followup_query,
            "thread_context": thread_context,
            "initial_message_count": len(initial_messages),
            "followup_message_count": len(followup_messages),
            "followup_thread_slug": followup_messages[-1].thread_url_slug if followup_messages else None,
            "followup_context_uuid": followup_messages[-1].frontend_context_uuid if followup_messages else None,
        }, f, indent=2)
    print(f"\nTest results saved to: {output_file}")


if __name__ == "__main__":
    main()

