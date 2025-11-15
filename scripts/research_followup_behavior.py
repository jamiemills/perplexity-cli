#!/usr/bin/env python3
"""Research how follow-ups actually work using Chrome DevTools Protocol.

This script will:
1. Navigate to a thread
2. Send a follow-up query in the browser
3. Capture the exact request and response
4. Understand how threads are structured after follow-ups
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import websockets
from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient


async def research_followup_on_thread(thread_hash: str):
    """Research follow-up behavior for a specific thread."""
    print("=" * 70)
    print(f"RESEARCHING FOLLOW-UP BEHAVIOR FOR THREAD: {thread_hash}")
    print("=" * 70)
    
    # Get thread info
    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.cli import find_thread_by_identifier
    
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
    
    print(f"\nThread: {thread.slug}")
    print(f"Title: {thread.title}")
    print(f"Current query_count: {thread.query_count}")
    
    client = ChromeDevToolsClient(port=9222)
    
    try:
        await client.connect()
        print("\n✓ Connected to Chrome")
        
        await client.send_command("Page.enable")
        await client.send_command("Runtime.enable")
        await client.send_command("Network.enable", {
            "maxResourceBufferSize": 1024 * 1024,
            "maxPostDataSize": 1024 * 1024
        })
        
        thread_url = f"https://www.perplexity.ai/search/{thread.slug}"
        print(f"\nNavigating to: {thread_url}")
        await client.send_command("Page.navigate", {"url": thread_url})
        
        print("Waiting for page to load...")
        await asyncio.sleep(8)
        
        # Get initial thread state
        print("\nExtracting initial thread state...")
        initial_state = await client.send_command("Runtime.evaluate", {
            "expression": """
            (function() {
                try {
                    // Count visible queries/messages
                    const queryElements = document.querySelectorAll('[class*="query"], [class*="message"], [data-query-id]');
                    const threadData = {
                        visibleQueries: queryElements.length,
                        threadSlug: window.location.pathname.split('/').pop(),
                    };
                    
                    // Try to get thread data from various sources
                    if (window.__NEXT_DATA__) {
                        threadData.nextData = window.__NEXT_DATA__;
                    }
                    
                    return threadData;
                } catch(e) {
                    return {error: e.message};
                }
            })()
            """
        })
        
        initial_data = initial_state.get("result", {}).get("value", {})
        print(f"Initial state: {json.dumps(initial_data, indent=2)}")
        
        # Monitor for follow-up request
        print("\n" + "=" * 70)
        print("MONITORING FOR FOLLOW-UP REQUEST")
        print("=" * 70)
        print("Please send a follow-up query in the browser now.")
        print("Waiting 60 seconds...")
        
        captured_request = None
        captured_response = None
        start_time = asyncio.get_event_loop().time()
        timeout = 60.0
        
        async def message_handler():
            nonlocal captured_request, captured_response
            while True:
                try:
                    message = await asyncio.wait_for(client.ws.recv(), timeout=1.0)
                    data = json.loads(message)
                    
                    if "method" in data:
                        method = data["method"]
                        params = data.get("params", {})
                        
                        if method == "Network.requestWillBeSent":
                            request = params.get("request", {})
                            url = request.get("url", "")
                            
                            if "/rest/sse/perplexity_ask" in url:
                                post_data = request.get("postData", "")
                                if post_data:
                                    try:
                                        captured_request = json.loads(post_data)
                                        print(f"\n{'='*70}")
                                        print("✓ CAPTURED FOLLOW-UP REQUEST")
                                        print(f"{'='*70}")
                                        print(json.dumps(captured_request, indent=2))
                                    except:
                                        pass
                        
                        elif method == "Network.responseReceived":
                            response = params.get("response", {})
                            url = response.get("url", "")
                            
                            if "/rest/sse/perplexity_ask" in url:
                                request_id = params.get("requestId")
                                # Try to get response body
                                try:
                                    body_result = await client.send_command("Network.getResponseBody", {
                                        "requestId": request_id
                                    })
                                    captured_response = body_result
                                    print(f"\n✓ Captured response for request")
                                except:
                                    pass
                    
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
        
        # Get final thread state
        print("\nExtracting final thread state...")
        await asyncio.sleep(3)  # Wait for page to update
        
        final_state = await client.send_command("Runtime.evaluate", {
            "expression": """
            (function() {
                try {
                    const queryElements = document.querySelectorAll('[class*="query"], [class*="message"], [data-query-id]');
                    return {
                        visibleQueries: queryElements.length,
                        threadSlug: window.location.pathname.split('/').pop(),
                    };
                } catch(e) {
                    return {error: e.message};
                }
            })()
            """
        })
        
        final_data = final_state.get("result", {}).get("value", {})
        print(f"Final state: {json.dumps(final_data, indent=2)}")
        
        # Save results
        output_file = Path(__file__).parent.parent / "docs" / f"followup_research_{thread_hash}.json"
        output_file.parent.mkdir(exist_ok=True)
        
        with open(output_file, "w") as f:
            json.dump({
                "thread_hash": thread_hash,
                "thread_slug": thread.slug,
                "initial_query_count": thread.query_count,
                "initial_state": initial_data,
                "captured_request": captured_request,
                "captured_response": captured_response,
                "final_state": final_data,
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/research_followup_behavior.py <thread_hash>")
        print("\nExample:")
        print("  python scripts/research_followup_behavior.py 1e8ef0ac")
        sys.exit(1)
    
    thread_hash = sys.argv[1]
    asyncio.run(research_followup_on_thread(thread_hash))

