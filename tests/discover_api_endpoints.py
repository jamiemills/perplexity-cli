#!/usr/bin/env python3
"""Discover available Perplexity API endpoints.

This script tests various endpoints to map out the API structure.
"""

import httpx

from perplexity_cli.auth.token_manager import TokenManager


def test_endpoints():
    """Test various potential API endpoints."""
    tm = TokenManager()
    token = tm.load_token()

    if not token:
        print("✗ No token found. Run: python save_auth_token.py")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "perplexity-cli/0.1.0",
        "Content-Type": "application/json",
    }

    endpoints = [
        # User/Auth endpoints
        ("GET", "https://www.perplexity.ai/api/user", "Get current user"),
        ("GET", "https://www.perplexity.ai/api/auth/session", "Get session info"),
        # Query/Search endpoints
        ("POST", "https://www.perplexity.ai/api/search", "Search endpoint"),
        ("POST", "https://www.perplexity.ai/api/query", "Query endpoint"),
        ("POST", "https://www.perplexity.ai/api/chat", "Chat endpoint"),
        # Library/History endpoints
        ("GET", "https://www.perplexity.ai/api/library", "Library API"),
        ("GET", "https://www.perplexity.ai/api/searches", "Saved searches"),
        ("GET", "https://www.perplexity.ai/api/history", "Search history"),
        # Collections/Threads
        ("GET", "https://www.perplexity.ai/api/collections", "Collections"),
        ("GET", "https://www.perplexity.ai/api/threads", "Conversation threads"),
        # Sources
        ("GET", "https://www.perplexity.ai/api/sources", "Source list"),
        # Settings
        ("GET", "https://www.perplexity.ai/api/settings", "User settings"),
    ]

    print("\n" + "=" * 80)
    print("  PERPLEXITY API ENDPOINT DISCOVERY")
    print("=" * 80 + "\n")

    results = {}

    for method, url, description in endpoints:
        print(f"{method:4} {url}")
        print(f"      Description: {description}")

        try:
            with httpx.Client() as client:
                if method == "GET":
                    response = client.get(url, headers=headers, timeout=10)
                else:
                    # For POST, send empty JSON body
                    response = client.post(url, headers=headers, json={}, timeout=10)

                status = response.status_code
                print(f"      Status: {status}")

                # Determine response type
                content_type = response.headers.get("content-type", "")
                is_json = "json" in content_type.lower()

                if status == 200:
                    if is_json:
                        try:
                            data = response.json()
                            if isinstance(data, dict):
                                keys = list(data.keys())[:5]
                                print(f"      ✓ JSON response (keys: {keys})")
                                results[url] = {"status": 200, "type": "json", "keys": keys}
                            elif isinstance(data, list):
                                print(f"      ✓ JSON array ({len(data)} items)")
                                results[url] = {
                                    "status": 200,
                                    "type": "json_array",
                                    "count": len(data),
                                }
                        except Exception:
                            print(f"      ✓ Response: {response.text[:100]}")
                    else:
                        text_preview = response.text[:100].replace("\n", " ")
                        print(f"      ✓ HTML/text response: {text_preview}...")
                        results[url] = {"status": 200, "type": "html"}

                elif status == 401:
                    print("      ✗ Unauthorized (token invalid)")
                    results[url] = {"status": 401, "type": "auth_error"}

                elif status == 403:
                    print("      ✗ Forbidden")
                    results[url] = {"status": 403, "type": "forbidden"}

                elif status == 404:
                    print("      ✗ Not found")
                    results[url] = {"status": 404, "type": "not_found"}

                elif status == 405:
                    print("      ✗ Method not allowed (try different HTTP method)")
                    results[url] = {"status": 405, "type": "method_not_allowed"}

                else:
                    print(f"      {status}")
                    results[url] = {"status": status, "type": "other"}

        except httpx.ConnectError as e:
            print(f"      Connection error: {e}")
            results[url] = {"status": "error", "type": "connection"}

        except Exception as e:
            print(f"      Error: {e}")
            results[url] = {"status": "error", "type": "exception"}

        print()

    # Summary
    print("\n" + "=" * 80)
    print("  SUMMARY")
    print("=" * 80 + "\n")

    working = [url for url, r in results.items() if r.get("status") == 200]
    not_found = [url for url, r in results.items() if r.get("status") == 404]
    forbidden = [url for url, r in results.items() if r.get("status") == 403]

    print(f"Working endpoints (200 OK): {len(working)}")
    for url in working:
        info = results[url]
        print(f"  ✓ {url}")
        if info.get("type") == "json":
            print(f"    Keys: {info.get('keys', [])}")

    print(f"\nNot found (404): {len(not_found)}")
    for url in not_found:
        print(f"  ✗ {url}")

    print(f"\nForbidden (403): {len(forbidden)}")
    for url in forbidden:
        print(f"  ✗ {url}")

    print("\n" + "=" * 80)
    print("  RECOMMENDATIONS FOR PHASE 3")
    print("=" * 80 + "\n")
    print("Use the working JSON endpoints above for Phase 3:")
    print("1. Identify which endpoint accepts queries")
    print("2. Determine request/response format")
    print("3. Implement query submission logic")
    print("4. Parse and extract answers from responses")
    print()


if __name__ == "__main__":
    test_endpoints()
