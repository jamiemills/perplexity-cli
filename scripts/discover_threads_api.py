#!/usr/bin/env python3
"""Discovery script to research Perplexity's library/threads API.

This script helps discover API endpoints and understand thread functionality.
Run with: python scripts/discover_threads_api.py
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.discovery import discover_library_endpoints, inspect_thread_from_response
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.logging import setup_logging


def main():
    """Run API discovery."""
    # Setup logging
    setup_logging(verbose=True)

    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        sys.exit(1)

    print("=" * 70)
    print("Perplexity Library/Threads API Discovery")
    print("=" * 70)
    print()

    # Discover library endpoints
    print("Step 1: Testing potential library endpoints...")
    print("-" * 70)
    results = discover_library_endpoints(token)

    print(f"\nTested {len(results['tested_endpoints'])} endpoints")
    print(f"Successful: {len(results['successful_endpoints'])}")
    print(f"Failed: {len(results['failed_endpoints'])}")

    if results["successful_endpoints"]:
        print("\n✓ Successful endpoints:")
        for endpoint in results["successful_endpoints"]:
            print(f"  {endpoint['url']} (Status: {endpoint['status']})")
            if "keys" in endpoint:
                print(f"    Response keys: {endpoint['keys']}")
            if "response_preview" in endpoint:
                print(f"    Preview: {endpoint['response_preview'][:200]}...")

    if results["failed_endpoints"]:
        print("\n✗ Failed endpoints:")
        for endpoint in results["failed_endpoints"]:
            print(f"  {endpoint.get('url', 'unknown')}: {endpoint.get('status', endpoint.get('error', 'unknown'))}")

    # Save results
    output_file = Path(__file__).parent.parent / "docs" / "api_discovery_results.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_file}")

    # Analyze existing query responses for thread info
    print("\n" + "=" * 70)
    print("Step 2: Analyzing existing query responses for thread information...")
    print("-" * 70)
    print("\nTo analyze thread info from a query:")
    print("1. Run: perplexity-cli query 'test query' --debug")
    print("2. Check the log file for SSE message data")
    print("3. Look for thread_url_slug, context_uuid fields")

    print("\n" + "=" * 70)
    print("Discovery complete!")
    print("=" * 70)


if __name__ == "__main__":
    main()

