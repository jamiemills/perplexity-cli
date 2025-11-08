#!/usr/bin/env python3
"""Simple test script to query Perplexity API."""

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager


def main():
    """Test querying Perplexity API."""
    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ No token found. Run: python tests/save_auth_token.py")
        return

    # Create API client
    print("Creating API client...")
    api = PerplexityAPI(token=token)

    # Submit a simple query
    query = "What is 2+2?"
    print(f"\nQuery: {query}")
    print("=" * 80)

    try:
        answer = api.get_complete_answer(query)
        print(f"\nAnswer:\n{answer}\n")
        print("=" * 80)
        print("✓ SUCCESS: Query completed and answer extracted")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
