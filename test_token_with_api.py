#!/usr/bin/env python3
"""Test that the extracted token works with Perplexity API.

This script tests whether the token obtained from authentication
can be used to make actual API requests to Perplexity.
"""

import json
import sys

import httpx

from perplexity_cli.auth.token_manager import TokenManager


def test_token_with_api() -> bool:
    """Test if the stored token can authenticate with Perplexity API."""
    print("\n" + "=" * 70)
    print("  TEST: Token Validity with Perplexity API")
    print("=" * 70 + "\n")

    # Load the stored token
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ No token found. Please run: python save_auth_token.py")
        return False

    print(f"Token loaded: {token[:50]}...")
    print(f"Token length: {len(token)} characters\n")

    # Test 1: Make a simple API request to check token validity
    print("TEST 1: Making authenticated request to Perplexity API")
    print("-" * 70)

    try:
        # Try to get user profile info (simple endpoint to verify auth)
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "perplexity-cli/0.1.0",
            "Content-Type": "application/json",
        }

        print("Headers being sent:")
        print(f"  Authorization: Bearer {token[:30]}...")
        print(f"  User-Agent: perplexity-cli/0.1.0")
        print(f"  Content-Type: application/json\n")

        with httpx.Client() as client:
            # Try common Perplexity API endpoints
            endpoints = [
                ("https://www.perplexity.ai/api/user", "GET", None),
                ("https://www.perplexity.ai/api/auth/session", "GET", None),
            ]

            for url, method, data in endpoints:
                print(f"Trying: {method} {url}")
                try:
                    if method == "GET":
                        response = client.get(url, headers=headers, timeout=10)
                    else:
                        response = client.post(url, headers=headers, json=data, timeout=10)

                    print(f"  Status: {response.status_code}")

                    if response.status_code == 200:
                        print(f"  ✓ SUCCESS: Token is valid!")
                        try:
                            data = response.json()
                            print(f"  Response: {json.dumps(data, indent=2)[:200]}...")
                        except:
                            print(f"  Response: {response.text[:200]}")
                        return True

                    elif response.status_code == 401:
                        print(f"  ✗ Unauthorized (401): Token may be invalid or expired")
                        print(f"  Response: {response.text[:200]}")

                    elif response.status_code == 403:
                        print(f"  ✗ Forbidden (403): Access denied")

                    elif response.status_code == 404:
                        print(f"  ✓ Endpoint not found (404): Try other endpoints")

                    else:
                        print(f"  Status {response.status_code}: {response.text[:100]}")

                except httpx.ConnectError as e:
                    print(f"  Connection error: {e}")
                except httpx.TimeoutException as e:
                    print(f"  Timeout: {e}")
                except Exception as e:
                    print(f"  Error: {e}")

                print()

        return False

    except Exception as e:
        print(f"✗ Error testing token: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_token_format() -> bool:
    """Verify the token format and structure."""
    print("\n" + "=" * 70)
    print("  TEST: Token Format and Structure")
    print("=" * 70 + "\n")

    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ No token found")
        return False

    print(f"Token content:")
    print(f"  Length: {len(token)} characters")
    print(f"  Format: {type(token)} (Python string)")
    print(f"  Preview: {token[:100]}...")
    print()

    # Check if it looks like a JWT
    if token.startswith("eyJ"):
        print("✓ Token appears to be JWT format (starts with 'eyJ')")
        parts = token.split(".")
        print(f"  JWT parts: {len(parts)}")
        if len(parts) >= 2:
            try:
                import base64
                header = base64.urlsafe_b64decode(parts[0] + "==")
                print(f"  Header: {header.decode()}")
            except:
                pass
    else:
        print("Token format: Unknown (not standard JWT)")

    print()

    # Check if stored correctly
    try:
        stored_data = None
        with open(tm.token_path) as f:
            stored_data = json.load(f)

        print(f"Stored data structure:")
        print(f"  Keys: {list(stored_data.keys())}")
        print(f"  Token key exists: {'token' in stored_data}")
        if "token" in stored_data:
            print(f"  Token matches loaded: {stored_data['token'] == token}")

        print()
        return True

    except Exception as e:
        print(f"✗ Error checking stored data: {e}")
        return False


def test_token_with_curl() -> bool:
    """Test token with curl and show commands."""
    print("\n" + "=" * 70)
    print("  TEST: Testing Additional Endpoints with curl")
    print("=" * 70 + "\n")

    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ No token found")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "perplexity-cli/0.1.0",
        "Content-Type": "application/json",
    }

    all_passed = True

    # Test additional endpoints
    endpoints = [
        ("https://www.perplexity.ai/api/auth/session", "Get session info"),
        ("https://www.perplexity.ai/api/conversations", "List conversations"),
    ]

    for url, description in endpoints:
        print(f"Testing: {description}")
        print(f"URL: {url}")

        try:
            with httpx.Client() as client:
                response = client.get(url, headers=headers, timeout=10)
                print(f"  Status: {response.status_code}")

                if response.status_code == 200:
                    print(f"  ✓ SUCCESS")
                    try:
                        data = response.json()
                        if isinstance(data, dict):
                            print(f"  Response keys: {list(data.keys())[:5]}")
                        elif isinstance(data, list):
                            print(f"  Response: List of {len(data)} items")
                        else:
                            print(f"  Response: {str(data)[:100]}")
                    except:
                        print(f"  Response: {response.text[:100]}")
                else:
                    print(f"  Status {response.status_code}")
                    print(f"  Response: {response.text[:200]}")
                    if response.status_code != 404:
                        all_passed = False

        except Exception as e:
            print(f"  Error: {e}")

        print()

    print("curl commands for manual testing:")
    print("-" * 70)
    print(f"""
# Get session info
curl -X GET 'https://www.perplexity.ai/api/auth/session' \\
  -H 'Authorization: Bearer {token}' \\
  -H 'User-Agent: perplexity-cli/0.1.0' \\
  -H 'Content-Type: application/json'

# List conversations
curl -X GET 'https://www.perplexity.ai/api/conversations' \\
  -H 'Authorization: Bearer {token}' \\
  -H 'User-Agent: perplexity-cli/0.1.0' \\
  -H 'Content-Type: application/json'
""")

    return all_passed


def main() -> None:
    """Run all token tests."""
    print("\n" + "=" * 70)
    print("  PERPLEXITY CLI - TOKEN VALIDATION TESTS")
    print("=" * 70)

    results = {}

    # Test token format
    results["Token Format"] = test_token_format()

    # Test token validity with API
    results["API Validity"] = test_token_with_api()

    # Show curl commands
    results["Curl Examples"] = test_token_with_curl()

    # Summary
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70 + "\n")

    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else "⚠️ N/A or NEEDS VERIFICATION"
        print(f"  {test_name}: {status}")

    print()
    print("NEXT STEPS:")
    print("-" * 70)
    print("1. Run curl commands above to verify token works")
    print("2. Check response status codes:")
    print("   - 200 OK: Token is valid ✓")
    print("   - 401 Unauthorized: Token is invalid or expired ✗")
    print("   - 403 Forbidden: Token valid but no permission ✗")
    print("4. If token is invalid, run: python save_auth_token.py")
    print()


if __name__ == "__main__":
    main()
