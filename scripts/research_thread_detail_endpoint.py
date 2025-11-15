#!/usr/bin/env python3
"""Research thread detail endpoints to understand thread structure.

This script tests various endpoints that might return detailed thread information,
including query counts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import httpx
import json
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import find_thread_by_identifier


def test_thread_detail_endpoints():
    """Test potential thread detail endpoints."""
    tm = TokenManager()
    token = tm.load_token()
    if not token:
        print("✗ Not authenticated")
        return
    
    api = PerplexityAPI(token=token)
    
    # Get a thread to test with
    thread = find_thread_by_identifier(api, "1e8ef0ac")
    if not thread:
        print("✗ Test thread not found")
        return
    
    print(f"Testing with thread: {thread.slug}")
    print(f"  Title: {thread.title}")
    print(f"  query_count (from list): {thread.query_count}")
    print()
    
    base_url = "https://www.perplexity.ai"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-app-apiversion": "2.18",
        "x-app-apiclient": "default",
    }
    
    # Potential endpoints to test
    endpoints_to_test = [
        f"/rest/thread/{thread.slug}",
        f"/rest/thread/get_thread?slug={thread.slug}",
        f"/rest/thread/detail?slug={thread.slug}",
        f"/api/thread/{thread.slug}",
        f"/api/threads/{thread.slug}",
        f"/rest/conversation/{thread.slug}",
        f"/rest/conversation/get?slug={thread.slug}",
        f"/rest/thread/thread_detail?slug={thread.slug}",
        f"/rest/thread/get_thread_detail?slug={thread.slug}",
        f"/rest/thread/list_thread_queries?slug={thread.slug}",
        f"/rest/thread/queries?thread_slug={thread.slug}",
    ]
    
    results = {}
    
    with httpx.Client(timeout=30) as client:
        for endpoint in endpoints_to_test:
            url = f"{base_url}{endpoint}"
            print(f"Testing: {endpoint}")
            
            # Try GET first
            try:
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        results[endpoint] = {
                            "method": "GET",
                            "status": response.status_code,
                            "response_keys": list(data.keys()) if isinstance(data, dict) else "not_dict",
                            "response_preview": str(data)[:500] if not isinstance(data, dict) else None,
                        }
                        print(f"  ✓ GET {response.status_code}")
                        if isinstance(data, dict) and "query_count" in data:
                            print(f"    query_count: {data.get('query_count')}")
                        if isinstance(data, dict) and "queries" in data:
                            queries = data.get("queries", [])
                            print(f"    queries array length: {len(queries)}")
                    except:
                        results[endpoint] = {
                            "method": "GET",
                            "status": response.status_code,
                            "error": "not_json",
                        }
                        print(f"  ✗ GET {response.status_code} (not JSON)")
                else:
                    results[endpoint] = {
                        "method": "GET",
                        "status": response.status_code,
                    }
                    print(f"  ✗ GET {response.status_code}")
            except Exception as e:
                results[endpoint] = {
                    "method": "GET",
                    "error": str(e),
                }
                print(f"  ✗ GET error: {e}")
            
            # Try POST with slug in body
            try:
                post_data = {"slug": thread.slug}
                response = client.post(url, headers=headers, json=post_data)
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if endpoint not in results or results[endpoint].get("status") != 200:
                            results[endpoint] = {
                                "method": "POST",
                                "status": response.status_code,
                                "response_keys": list(data.keys()) if isinstance(data, dict) else "not_dict",
                            }
                            print(f"  ✓ POST {response.status_code}")
                            if isinstance(data, dict) and "query_count" in data:
                                print(f"    query_count: {data.get('query_count')}")
                            if isinstance(data, dict) and "queries" in data:
                                queries = data.get("queries", [])
                                print(f"    queries array length: {len(queries)}")
                    except:
                        if endpoint not in results:
                            results[endpoint] = {
                                "method": "POST",
                                "status": response.status_code,
                                "error": "not_json",
                            }
            except Exception as e:
                if endpoint not in results:
                    results[endpoint] = {
                        "method": "POST",
                        "error": str(e),
                    }
            
            print()
    
    # Save results
    output_file = Path(__file__).parent.parent / "docs" / "thread_detail_endpoints.json"
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, "w") as f:
        json.dump({
            "test_thread": {
                "slug": thread.slug,
                "title": thread.title,
                "query_count_from_list": thread.query_count,
            },
            "endpoint_results": results,
        }, f, indent=2)
    
    print(f"✓ Results saved to: {output_file}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    working_endpoints = [ep for ep, res in results.items() if res.get("status") == 200]
    if working_endpoints:
        print(f"\n✓ Found {len(working_endpoints)} working endpoint(s):")
        for ep in working_endpoints:
            print(f"  - {ep}")
    else:
        print("\n✗ No working thread detail endpoints found")
        print("  May need to inspect browser network requests to find correct endpoint")


if __name__ == "__main__":
    test_thread_detail_endpoints()

