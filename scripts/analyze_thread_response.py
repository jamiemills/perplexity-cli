#!/usr/bin/env python3
"""Analyze a real query response to extract thread information.

This script submits a test query and analyzes the SSE messages for thread-related fields.
Run with: python scripts/analyze_thread_response.py
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.discovery import inspect_thread_from_response
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.logging import setup_logging


def main():
    """Analyze query response for thread information."""
    setup_logging(verbose=True)

    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        sys.exit(1)

    print("=" * 70)
    print("Thread Information Analysis")
    print("=" * 70)
    print()

    api = PerplexityAPI(token=token)

    # Submit a test query
    test_query = "What is Python?"
    print(f"Submitting test query: '{test_query}'")
    print("-" * 70)

    thread_info_found = {}
    all_messages = []

    try:
        for message in api.submit_query(test_query):
            # Convert message to dict for inspection
            message_dict = {
                "thread_url_slug": message.thread_url_slug,
                "context_uuid": message.context_uuid,
                "frontend_context_uuid": message.frontend_context_uuid,
                "backend_uuid": message.backend_uuid,
                "uuid": message.uuid,
                "cursor": message.cursor,
                "read_write_token": message.read_write_token,
                "status": message.status,
                "final_sse_message": message.final_sse_message,
            }

            all_messages.append(message_dict)

            # Inspect for thread info
            thread_info = inspect_thread_from_response(message_dict)
            if thread_info["found_fields"]:
                thread_info_found = thread_info
                print(f"\n✓ Thread information found in message:")
                print(f"  Fields: {thread_info['found_fields']}")
                if thread_info["thread_identifiers"]:
                    print(f"  Thread identifiers: {thread_info['thread_identifiers']}")
                if thread_info["context_fields"]:
                    print(f"  Context fields: {thread_info['context_fields']}")

            if message.final_sse_message:
                print(f"\n✓ Final message received")
                break

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total messages received: {len(all_messages)}")

    if thread_info_found:
        print("\n✓ Thread information extracted:")
        print(json.dumps(thread_info_found, indent=2))
    else:
        print("\n⚠ No thread information found in response")

    # Save raw message data
    output_file = Path(__file__).parent.parent / "docs" / "thread_response_analysis.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({
            "query": test_query,
            "messages": all_messages,
            "thread_info": thread_info_found,
        }, f, indent=2)
    print(f"\nFull analysis saved to: {output_file}")


if __name__ == "__main__":
    main()

