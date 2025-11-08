#!/usr/bin/env python3
"""Test actual query submission to see SSE response structure."""

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager


def main():
    """Test query and print all SSE messages."""
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ No token found. Run: python tests/save_auth_token.py")
        return

    print("Creating API client...")
    api = PerplexityAPI(token=token)

    print("\nSubmitting query: 'What is 2+2?'\n")
    print("=" * 80)

    message_count = 0
    for message in api.submit_query("What is 2+2?"):
        message_count += 1
        print(f"\n--- Message {message_count} ---")
        print(f"Status: {message.status}")
        print(f"Text completed: {message.text_completed}")
        print(f"Final message: {message.final_sse_message}")
        print(f"Blocks: {len(message.blocks)}")

        for i, block in enumerate(message.blocks):
            print(f"\n  Block {i}:")
            print(f"    Intended usage: {block.intended_usage}")
            print(f"    Content keys: {list(block.content.keys())[:5]}")

            # Print first 200 chars of content
            import json

            content_str = json.dumps(block.content, indent=2)
            print(f"    Content preview: {content_str[:300]}...")

        if message.final_sse_message:
            print("\n✓ Stream complete (final_sse_message: true)")
            break

    print(f"\n\nTotal messages received: {message_count}")

    # Now test get_complete_answer
    print("\n" + "=" * 80)
    print("Testing get_complete_answer()...\n")

    answer = api.get_complete_answer("What is 2+2?")
    print(f"Answer: {repr(answer)}")
    print(f"Answer length: {len(answer)}")

    if answer:
        print(f"\nAnswer text:\n{answer}")
    else:
        print("\n⚠️ Answer is empty - need to fix text extraction logic")


if __name__ == "__main__":
    main()
