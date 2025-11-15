#!/usr/bin/env python3
"""Compare our follow-up request with browser's actual request.

This script:
1. Gets a thread by hash/slug
2. Makes a follow-up request using our code
3. Captures what we actually send
4. Compares with browser request (if available)
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.api.models import QueryParams, QueryRequest
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import find_thread_by_identifier


async def capture_our_request(thread_hash: str, query: str):
    """Capture what our code sends for a follow-up request."""
    print("=" * 70)
    print("CAPTURING OUR FOLLOW-UP REQUEST")
    print("=" * 70)
    
    # Load token
    tm = TokenManager()
    token = tm.load_token()
    if not token:
        print("✗ Not authenticated. Run: perplexity-cli auth")
        return None
    
    api = PerplexityAPI(token=token)
    
    # Find thread
    print(f"Finding thread by hash: {thread_hash}")
    found_thread = find_thread_by_identifier(api, thread_hash)
    
    if not found_thread:
        print(f"✗ Thread not found for hash: {thread_hash}")
        return None
    
    print(f"✓ Found thread: {found_thread.slug}")
    print(f"  Title: {found_thread.title}")
    print(f"  frontend_context_uuid: {found_thread.frontend_context_uuid}")
    print(f"  context_uuid: {found_thread.context_uuid}")
    print(f"  read_write_token: {found_thread.read_write_token[:20] if found_thread.read_write_token else None}...")
    print(f"  slug: {found_thread.slug}")
    print(f"  last_query_datetime: {found_thread.last_query_datetime}")
    
    # Get thread context (simulating what followup command does)
    from perplexity_cli.utils.thread_context import load_thread_context
    from datetime import datetime
    
    thread_context = load_thread_context(found_thread.slug)
    
    if not thread_context:
        print("\n⚠ No cached context, fetching latest thread context...")
        # Simulate the logic from followup command
        target_context_uuid = found_thread.frontend_context_uuid
        
        all_threads = api.list_threads(limit=100, offset=0, search_term="")
        
        matching_threads = [
            t for t in all_threads 
            if t.frontend_context_uuid == target_context_uuid
        ]
        
        if matching_threads:
            def parse_datetime(dt_str: str) -> datetime:
                try:
                    if dt_str.endswith("Z"):
                        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    return datetime.fromisoformat(dt_str)
                except (ValueError, AttributeError):
                    return datetime.fromtimestamp(0)
            
            matching_threads.sort(
                key=lambda t: parse_datetime(t.last_query_datetime),
                reverse=True
            )
            latest_thread = matching_threads[0]
            print(f"  Found {len(matching_threads)} threads with same frontend_context_uuid")
            print(f"  Using latest: {latest_thread.slug}")
            thread_context = latest_thread.to_thread_context()
        else:
            thread_context = found_thread.to_thread_context()
    
    print(f"\n✓ Using thread context:")
    print(f"  frontend_context_uuid: {thread_context.frontend_context_uuid}")
    print(f"  context_uuid: {thread_context.context_uuid}")
    print(f"  read_write_token: {thread_context.read_write_token[:20] if thread_context.read_write_token else None}...")
    print(f"  thread_url_slug: {thread_context.thread_url_slug}")
    
    # Build request (what we would send)
    import uuid
    frontend_uuid = str(uuid.uuid4())
    
    params = QueryParams(
        language="en-US",
        timezone="Europe/London",
        frontend_uuid=frontend_uuid,
        frontend_context_uuid=thread_context.frontend_context_uuid,
        context_uuid=thread_context.context_uuid if thread_context.context_uuid else None,
        read_write_token=thread_context.read_write_token if thread_context.read_write_token else None,
        thread_url_slug=thread_context.thread_url_slug if thread_context.thread_url_slug else None,
        is_related_query=True,
    )
    
    request = QueryRequest(query_str=query, params=params)
    request_dict = request.to_dict()
    
    print(f"\n{'='*70}")
    print("OUR REQUEST PAYLOAD")
    print(f"{'='*70}")
    print(json.dumps(request_dict, indent=2))
    
    # Extract key fields
    our_params = request_dict.get("params", {})
    print(f"\n{'='*70}")
    print("KEY FIELDS IN OUR REQUEST")
    print(f"{'='*70}")
    key_fields = {
        "frontend_uuid": our_params.get("frontend_uuid"),
        "frontend_context_uuid": our_params.get("frontend_context_uuid"),
        "context_uuid": our_params.get("context_uuid"),
        "read_write_token": our_params.get("read_write_token"),
        "thread_url_slug": our_params.get("thread_url_slug"),
        "is_related_query": our_params.get("is_related_query"),
    }
    for k, v in key_fields.items():
        if v is not None:
            print(f"  ✓ {k}: {v}")
        else:
            print(f"  ✗ {k}: NOT PRESENT")
    
    return {
        "thread_slug": found_thread.slug,
        "thread_hash": thread_hash,
        "our_request": request_dict,
        "key_fields": key_fields,
    }


async def compare_with_browser(browser_request_file: Path):
    """Compare our request with browser request."""
    if not browser_request_file.exists():
        print(f"\n⚠ Browser request file not found: {browser_request_file}")
        print("  Run inspect_followup_request.py first to capture browser request")
        return
    
    print(f"\n{'='*70}")
    print("COMPARING WITH BROWSER REQUEST")
    print(f"{'='*70}")
    
    with open(browser_request_file) as f:
        browser_data = json.load(f)
    
    browser_requests = browser_data.get("captured_requests", [])
    if not browser_requests:
        print("  No browser requests found in file")
        return
    
    # Find the actual query request
    query_requests = [
        r for r in browser_requests
        if r.get("postDataParsed") and "/rest/sse/perplexity_ask" in r.get("url", "")
    ]
    
    if not query_requests:
        print("  No query requests found")
        return
    
    browser_req = query_requests[0]
    browser_params = browser_req.get("postDataParsed", {}).get("params", {})
    
    print(f"\nBrowser request params:")
    browser_key_fields = {
        "frontend_uuid": browser_params.get("frontend_uuid"),
        "frontend_context_uuid": browser_params.get("frontend_context_uuid"),
        "context_uuid": browser_params.get("context_uuid"),
        "read_write_token": browser_params.get("read_write_token"),
        "thread_url_slug": browser_params.get("thread_url_slug"),
        "is_related_query": browser_params.get("is_related_query"),
    }
    for k, v in browser_key_fields.items():
        if v is not None:
            print(f"  ✓ {k}: {v}")
        else:
            print(f"  ✗ {k}: NOT PRESENT")
    
    # Compare
    print(f"\n{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}")
    
    # This will be populated by capture_our_request
    # For now, just show browser request
    print("\nBrowser request (full params):")
    print(json.dumps(browser_params, indent=2))


async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/compare_followup_requests.py <thread_hash> <query>")
        print("\nExample:")
        print("  python scripts/compare_followup_requests.py 6488e0e2 'how many people are in france'")
        sys.exit(1)
    
    thread_hash = sys.argv[1]
    query = sys.argv[2]
    
    our_data = await capture_our_request(thread_hash, query)
    
    # Try to compare with browser request if available
    browser_file = Path(__file__).parent.parent / "docs" / "followup_request_analysis.json"
    if browser_file.exists():
        await compare_with_browser(browser_file)
    
    # Save our request
    output_file = Path(__file__).parent.parent / "docs" / "our_followup_request.json"
    output_file.parent.mkdir(exist_ok=True)
    if our_data:
        with open(output_file, "w") as f:
            json.dump(our_data, f, indent=2)
        print(f"\n✓ Our request saved to: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())

