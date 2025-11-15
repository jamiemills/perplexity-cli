#!/usr/bin/env python3
"""Test the fixed follow-up query implementation.

This script tests that follow-up queries properly link to existing threads
by including all required context fields.
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import QueryParams
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.logging import setup_logging


def main():
    """Test follow-up query with all context fields."""
    setup_logging(verbose=True)

    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        sys.exit(1)

    print("=" * 70)
    print("Testing Follow-up Query Fix")
    print("=" * 70)
    print()

    api = PerplexityAPI(token=token)

    # Step 1: Initial query
    initial_query = "What is Python?"
    print(f"Step 1: Sending initial query: '{initial_query}'")
    print("-" * 70)

    initial_thread_slug = None
    initial_context_uuid = None
    initial_frontend_context_uuid = None
    initial_read_write_token = None

    try:
        for message in api.submit_query(initial_query):
            if message.final_sse_message:
                initial_thread_slug = message.thread_url_slug
                initial_context_uuid = message.context_uuid
                initial_frontend_context_uuid = message.frontend_context_uuid
                initial_read_write_token = message.read_write_token
                print(f"\n✓ Initial query complete")
                print(f"  Thread slug: {initial_thread_slug}")
                print(f"  Frontend context UUID: {initial_frontend_context_uuid}")
                print(f"  Backend context UUID: {initial_context_uuid}")
                print(f"  Read-write token: {'Present' if initial_read_write_token else 'None'}")
                break
    except Exception as e:
        print(f"\n✗ Error in initial query: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if not initial_frontend_context_uuid:
        print("\n✗ Failed to extract context from initial query")
        sys.exit(1)

    # Step 2: Check request parameters for follow-up
    print(f"\nStep 2: Testing follow-up query parameters")
    print("-" * 70)

    from perplexity_cli.api.models import ThreadContext, QueryRequest
    import uuid

    thread_context = ThreadContext(
        thread_url_slug=initial_thread_slug or "",
        frontend_context_uuid=initial_frontend_context_uuid,
        context_uuid=initial_context_uuid,
        read_write_token=initial_read_write_token,
    )

    # Build follow-up params
    params = QueryParams(
        frontend_uuid=str(uuid.uuid4()),
        frontend_context_uuid=thread_context.frontend_context_uuid,
        context_uuid=thread_context.context_uuid if thread_context.context_uuid else None,
        read_write_token=thread_context.read_write_token if thread_context.read_write_token else None,
        is_related_query=True,
    )

    params_dict = params.to_dict()
    print("Follow-up query parameters:")
    print(f"  frontend_context_uuid: {params_dict.get('frontend_context_uuid')}")
    print(f"  context_uuid: {params_dict.get('context_uuid', 'NOT INCLUDED')}")
    print(f"  read_write_token: {params_dict.get('read_write_token', 'NOT INCLUDED')}")
    print(f"  is_related_query: {params_dict.get('is_related_query')}")

    # Verify all fields are included
    has_context_uuid = "context_uuid" in params_dict
    has_read_write_token = "read_write_token" in params_dict

    print(f"\n✓ Context UUID included: {has_context_uuid}")
    print(f"✓ Read-write token included: {has_read_write_token}")

    if has_context_uuid and has_read_write_token:
        print("\n✓ All required context fields are included in follow-up request!")
    elif has_context_uuid:
        print("\n⚠ Context UUID included, but read-write token missing (may be OK if token was None)")
    else:
        print("\n✗ Missing required context fields!")

    # Step 3: Send actual follow-up query
    followup_query = "What are its main features?"
    print(f"\nStep 3: Sending follow-up query: '{followup_query}'")
    print("-" * 70)

    followup_thread_slug = None
    followup_context_uuid = None
    followup_frontend_context_uuid = None

    try:
        for message in api.submit_followup_query(followup_query, thread_context):
            if message.final_sse_message:
                followup_thread_slug = message.thread_url_slug
                followup_context_uuid = message.context_uuid
                followup_frontend_context_uuid = message.frontend_context_uuid
                print(f"\n✓ Follow-up query complete")
                print(f"  Thread slug: {followup_thread_slug}")
                print(f"  Frontend context UUID: {followup_frontend_context_uuid}")
                print(f"  Backend context UUID: {followup_context_uuid}")
                break
    except Exception as e:
        print(f"\n✗ Error in follow-up query: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 4: Verify thread continuity
    print(f"\nStep 4: Verifying thread continuity")
    print("-" * 70)

    context_matches = (
        followup_frontend_context_uuid == initial_frontend_context_uuid
    )
    backend_context_matches = (
        followup_context_uuid == initial_context_uuid
    )

    print(f"Frontend context UUID matches: {context_matches}")
    print(f"Backend context UUID matches: {backend_context_matches}")

    if context_matches and backend_context_matches:
        print("\n✓ Thread continuity verified! Follow-up query properly linked.")
    elif context_matches:
        print("\n⚠ Frontend context matches, but backend context differs (may be expected)")
    else:
        print("\n✗ Thread context does not match - follow-up may not be linked")

    # Save test results
    output_file = Path(__file__).parent.parent / "docs" / "followup_fix_test_results.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({
            "initial_query": initial_query,
            "followup_query": followup_query,
            "initial_context": {
                "thread_slug": initial_thread_slug,
                "frontend_context_uuid": initial_frontend_context_uuid,
                "context_uuid": initial_context_uuid,
                "read_write_token": initial_read_write_token is not None,
            },
            "followup_context": {
                "thread_slug": followup_thread_slug,
                "frontend_context_uuid": followup_frontend_context_uuid,
                "context_uuid": followup_context_uuid,
            },
            "continuity_check": {
                "frontend_context_matches": context_matches,
                "backend_context_matches": backend_context_matches,
            },
            "request_params": {
                "has_context_uuid": has_context_uuid,
                "has_read_write_token": has_read_write_token,
            },
        }, f, indent=2)
    print(f"\nTest results saved to: {output_file}")


if __name__ == "__main__":
    main()

