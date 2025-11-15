#!/usr/bin/env python3
"""Test the discovered library API endpoints.

Tests the actual endpoints found from inspecting the library page.
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.config import get_perplexity_base_url
from perplexity_cli.utils.logging import setup_logging


def main():
    """Test library endpoints."""
    setup_logging(verbose=True)

    # Load token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        sys.exit(1)

    print("=" * 70)
    print("Testing Library API Endpoints")
    print("=" * 70)
    print()

    base_url = get_perplexity_base_url()
    
    # Parse token (it's stored as JSON string)
    try:
        token_data = json.loads(token)
        # Extract actual token from session data
        if isinstance(token_data, dict) and "user" in token_data:
            # Use the session token directly
            auth_token = token
        else:
            auth_token = token
    except json.JSONDecodeError:
        auth_token = token

    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "perplexity-cli/0.1.0",
    }

    # Test 1: List threads
    print("Test 1: List threads")
    print("-" * 70)
    list_threads_url = f"{base_url}/rest/thread/list_ask_threads?version=2.18&source=default"
    
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(list_threads_url, headers=headers, json={})
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Success! Response keys: {list(data.keys()) if isinstance(data, dict) else 'not_dict'}")
                
                # Save response
                output_file = Path(__file__).parent.parent / "docs" / "list_threads_response.json"
                output_file.parent.mkdir(exist_ok=True)
                with open(output_file, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"Response saved to: {output_file}")
                
                # Print summary
                if isinstance(data, dict):
                    if "threads" in data:
                        print(f"  Found {len(data['threads'])} threads")
                    elif "data" in data:
                        print(f"  Found data: {type(data['data'])}")
            else:
                print(f"✗ Failed: {response.text[:200]}")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

    print()

    # Test 2: List collections
    print("Test 2: List collections")
    print("-" * 70)
    list_collections_url = f"{base_url}/rest/collections/list_user_collections?limit=30&offset=0&version=2.18&source=default"
    
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(list_collections_url, headers=headers)
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Success! Response keys: {list(data.keys()) if isinstance(data, dict) else 'not_dict'}")
                
                # Save response
                output_file = Path(__file__).parent.parent / "docs" / "list_collections_response.json"
                output_file.parent.mkdir(exist_ok=True)
                with open(output_file, "w") as f:
                    json.dump(data, f, indent=2)
                print(f"Response saved to: {output_file}")
            else:
                print(f"✗ Failed: {response.text[:200]}")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

