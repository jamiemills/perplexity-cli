#!/usr/bin/env python3
"""Research thread structure using Chrome DevTools Protocol.

This script will:
1. Navigate to specific threads
2. Inspect their structure
3. Count actual queries/messages
4. Understand how follow-ups work
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import websockets
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.cli import find_thread_by_identifier


async def inspect_thread_structure(thread_hash: str):
    """Inspect a thread's structure using CDP."""
    print("=" * 70)
    print(f"INSPECTING THREAD: {thread_hash}")
    print("=" * 70)
    
    # Get thread info from API
    tm = TokenManager()
    token = tm.load_token()
    if not token:
        print("✗ Not authenticated")
        return
    
    api = PerplexityAPI(token=token)
    thread = find_thread_by_identifier(api, thread_hash)
    
    if not thread:
        print(f"✗ Thread not found: {thread_hash}")
        return
    
    print(f"\nThread Info from API:")
    print(f"  Slug: {thread.slug}")
    print(f"  Title: {thread.title}")
    print(f"  query_count: {thread.query_count}")
    print(f"  frontend_context_uuid: {thread.frontend_context_uuid}")
    print(f"  context_uuid: {thread.context_uuid}")
    print(f"  total_threads: {thread.total_threads}")
    
    # Navigate to thread page using CDP
    from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient
    
    client = ChromeDevToolsClient(port=9222)
    
    try:
        await client.connect()
        print("\n✓ Connected to Chrome")
        
        await client.send_command("Page.enable")
        await client.send_command("Runtime.enable")
        await client.send_command("Network.enable")
        
        thread_url = f"https://www.perplexity.ai/thread/{thread.slug}"
        print(f"\nNavigating to: {thread_url}")
        await client.send_command("Page.navigate", {"url": thread_url})
        
        print("Waiting for page to load...")
        await asyncio.sleep(5)
        
        # Extract thread structure from page
        print("\nExtracting thread structure from page...")
        
        # Get all queries/messages in the thread
        result = await client.send_command("Runtime.evaluate", {
            "expression": """
            (function() {
                try {
                    // Look for thread data in various places
                    const data = {
                        threadSlug: window.location.pathname.split('/').pop(),
                        queries: [],
                        messages: [],
                        threadData: null
                    };
                    
                    // Try to find thread data in React state, localStorage, or window
                    // Look for message/query containers
                    const messageElements = document.querySelectorAll('[data-message-id], [class*="message"], [class*="query"], [class*="thread"]');
                    data.messageElements = messageElements.length;
                    
                    // Try to find thread data in window object
                    if (window.__NEXT_DATA__) {
                        data.nextData = window.__NEXT_DATA__;
                    }
                    
                    // Look for thread structure in DOM
                    const threadContainer = document.querySelector('[class*="thread"], [id*="thread"]');
                    if (threadContainer) {
                        const queryContainers = threadContainer.querySelectorAll('[class*="query"], [class*="message"]');
                        data.queryContainers = queryContainers.length;
                    }
                    
                    return data;
                } catch(e) {
                    return {error: e.message};
                }
            })()
            """
        })
        
        page_data = result.get("result", {}).get("value", {})
        print(f"\nPage data extracted:")
        print(json.dumps(page_data, indent=2))
        
        # Try to get network requests to understand API calls
        print("\n" + "=" * 70)
        print("MONITORING NETWORK REQUESTS")
        print("=" * 70)
        print("Please interact with the thread (scroll, expand messages, etc.)")
        print("Waiting 30 seconds to capture API calls...")
        
        captured_requests = []
        start_time = asyncio.get_event_loop().time()
        timeout = 30.0
        
        async def message_handler():
            while True:
                try:
                    message = await asyncio.wait_for(client.ws.recv(), timeout=1.0)
                    data = json.loads(message)
                    
                    if "method" in data and data["method"] == "Network.requestWillBeSent":
                        request = data.get("params", {}).get("request", {})
                        url = request.get("url", "")
                        
                        # Look for thread-related API calls
                        if any(keyword in url.lower() for keyword in ["thread", "query", "message", "conversation"]):
                            captured_requests.append({
                                "url": url,
                                "method": request.get("method"),
                                "headers": {k: v for k, v in request.get("headers", {}).items() if k.lower() not in ["authorization", "cookie"]},
                            })
                            print(f"\n✓ Captured request: {request.get('method')} {url}")
                    
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    continue
        
        try:
            await asyncio.wait_for(message_handler(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        
        print(f"\n✓ Captured {len(captured_requests)} thread-related requests")
        
        # Save results
        output_file = Path(__file__).parent.parent / "docs" / f"thread_research_{thread_hash}.json"
        output_file.parent.mkdir(exist_ok=True)
        
        with open(output_file, "w") as f:
            json.dump({
                "thread_hash": thread_hash,
                "thread_slug": thread.slug,
                "api_thread_info": {
                    "title": thread.title,
                    "query_count": thread.query_count,
                    "frontend_context_uuid": thread.frontend_context_uuid,
                    "context_uuid": thread.context_uuid,
                    "total_threads": thread.total_threads,
                },
                "page_data": page_data,
                "captured_requests": captured_requests,
            }, f, indent=2)
        
        print(f"\n✓ Results saved to: {output_file}")
        
        await client.close()
        
    except ConnectionRefusedError:
        print("✗ Cannot connect to Chrome DevTools")
        print("  Make sure Chrome is running with: --remote-debugging-port=9222")
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()


async def research_all_threads():
    """Research all three threads."""
    threads = ["1e8ef0ac", "1f344d10", "b4cf5f8d"]
    
    for thread_hash in threads:
        await inspect_thread_structure(thread_hash)
        print("\n" + "=" * 70 + "\n")
        await asyncio.sleep(2)  # Brief pause between threads


if __name__ == "__main__":
    asyncio.run(research_all_threads())

