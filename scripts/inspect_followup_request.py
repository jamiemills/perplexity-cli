#!/usr/bin/env python3
"""Inspect actual follow-up query requests from Perplexity browser.

This script uses Chrome DevTools Protocol to:
1. Navigate to an existing thread
2. Monitor network requests
3. Capture the exact payload sent when sending a follow-up query
4. Compare with our implementation

Run with: python scripts/inspect_followup_request.py <thread_slug>
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import websockets
from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient
from perplexity_cli.auth.token_manager import TokenManager


async def inspect_followup_request(thread_slug: str):
    """Capture follow-up query request from browser."""
    print("=" * 70)
    print("Inspecting Follow-up Query Request")
    print("=" * 70)
    print(f"Thread slug: {thread_slug}")
    print()
    
    client = ChromeDevToolsClient(port=9222)
    
    try:
        print("Connecting to Chrome...")
        await client.connect()
        print("✓ Connected to Chrome")
        
        # Enable Network domain with request interception
        await client.send_command("Network.enable", {
            "maxResourceBufferSize": 1024 * 1024,
            "maxPostDataSize": 1024 * 1024
        })
        print("✓ Network domain enabled")
        
        # Enable Page domain
        await client.send_command("Page.enable")
        print("✓ Page domain enabled")
        
        # Enable Runtime domain to execute JavaScript
        await client.send_command("Runtime.enable")
        print("✓ Runtime domain enabled")
        
        # Navigate to thread page
        thread_url = f"https://www.perplexity.ai/thread/{thread_slug}"
        print(f"\nNavigating to thread: {thread_url}")
        await client.send_command("Page.navigate", {"url": thread_url})
        
        # Wait for page to load
        print("Waiting for page to load...")
        await asyncio.sleep(8)  # Give more time for page to fully load
        
        # Set up request collection
        captured_requests = []
        request_ids = {}  # Map requestId to request data
        
        # Try to find the input field and prepare for interaction
        print("\nPage loaded. Looking for query input field...")
        try:
            # Check if page is ready
            result = await client.send_command("Runtime.evaluate", {
                "expression": "document.readyState"
            })
            print(f"Page ready state: {result.get('result', {}).get('value', 'unknown')}")
        except Exception as e:
            print(f"Could not check page state: {e}")
        
        print("\n" + "=" * 70)
        print("MONITORING NETWORK REQUESTS")
        print("=" * 70)
        print("Please send a follow-up query in the browser now.")
        print("The script will capture the exact request payload.")
        print("Waiting 90 seconds for you to interact...")
        print("-" * 70)
        
        # Collect requests for 90 seconds
        start_time = asyncio.get_event_loop().time()
        timeout = 90.0
        
        # Set up message handler task
        async def message_handler():
            while True:
                try:
                    message = await client.ws.recv()
                    data = json.loads(message)
                    
                    # Skip command responses (they have "id" field)
                    if "id" in data and "method" not in data:
                        continue
                    
                    # Handle network request events
                    if "method" in data:
                        method = data["method"]
                        params = data.get("params", {})
                        
                        if method == "Network.requestWillBeSent":
                            request = params.get("request", {})
                            request_id = params.get("requestId")
                            url = request.get("url", "")
                            
                            # Look for query API endpoint
                            if "/rest/sse/perplexity_ask" in url or "/api/chat" in url or "perplexity_ask" in url or "perplexity" in url.lower():
                                post_data = request.get("postData", "")
                                headers = request.get("headers", {})
                                
                                elapsed = asyncio.get_event_loop().time() - start_time
                                
                                request_info = {
                                    "requestId": request_id,
                                    "url": url,
                                    "method": request.get("method", ""),
                                    "headers": {k: v for k, v in headers.items() if k.lower() not in ["authorization", "cookie"]},  # Exclude sensitive headers
                                    "postData": post_data,
                                    "timestamp": elapsed,
                                }
                                
                                request_ids[request_id] = request_info
                                captured_requests.append(request_info)
                                
                                print(f"\n{'='*70}")
                                print(f"✓ CAPTURED REQUEST at {elapsed:.1f}s")
                                print(f"{'='*70}")
                                print(f"URL: {url}")
                                print(f"Method: {request.get('method')}")
                                
                                # Try to parse postData as JSON
                                if post_data:
                                    try:
                                        post_json = json.loads(post_data)
                                        print(f"\nRequest payload structure:")
                                        print(f"  Top-level keys: {list(post_json.keys())}")
                                        
                                        if "params" in post_json:
                                            params_dict = post_json.get("params", {})
                                            print(f"\n  Params keys ({len(params_dict)} total):")
                                            
                                            # Show ALL params for debugging
                                            for key in sorted(params_dict.keys()):
                                                value = params_dict[key]
                                                if isinstance(value, str) and len(value) > 50:
                                                    print(f"    {key}: {value[:50]}... (length: {len(value)})")
                                                else:
                                                    print(f"    {key}: {value}")
                                            
                                            # Highlight key context fields
                                            print(f"\n  KEY CONTEXT FIELDS:")
                                            context_fields = {
                                                "frontend_context_uuid": params_dict.get("frontend_context_uuid"),
                                                "context_uuid": params_dict.get("context_uuid"),
                                                "read_write_token": params_dict.get("read_write_token"),
                                                "is_related_query": params_dict.get("is_related_query"),
                                                "thread_url_slug": params_dict.get("thread_url_slug"),
                                                "frontend_uuid": params_dict.get("frontend_uuid"),
                                            }
                                            for k, v in context_fields.items():
                                                if v is not None:
                                                    print(f"    ✓ {k}: {v}")
                                                else:
                                                    print(f"    ✗ {k}: NOT PRESENT")
                                            
                                            # Check query_str
                                            query_str = post_json.get("query_str", "")
                                            print(f"\n  Query: {query_str[:100]}...")
                                            
                                    except json.JSONDecodeError as e:
                                        print(f"  Post data (raw, first 500 chars): {post_data[:500]}...")
                                        print(f"  JSON parse error: {e}")
                                else:
                                    print("  ⚠ No postData found")
                        
                        elif method == "Network.responseReceived":
                            request_id = params.get("requestId")
                            if request_id in request_ids:
                                response = params.get("response", {})
                                request_ids[request_id]["responseStatus"] = response.get("status")
                                request_ids[request_id]["responseHeaders"] = response.get("headers", {})
                
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    print(f"  Error processing message: {e}")
                    continue
        
        # Run message handler with timeout
        try:
            await asyncio.wait_for(message_handler(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        
        print(f"\n✓ Collection complete. Captured {len(captured_requests)} requests")
        
        # Save results
        output_file = Path(__file__).parent.parent / "docs" / "followup_request_analysis.json"
        output_file.parent.mkdir(exist_ok=True)
        
        # Parse postData for each request
        parsed_requests = []
        for req in captured_requests:
            parsed_req = req.copy()
            if req.get("postData"):
                try:
                    parsed_req["postDataParsed"] = json.loads(req["postData"])
                except json.JSONDecodeError:
                    parsed_req["postDataParsed"] = None
            parsed_requests.append(parsed_req)
        
        with open(output_file, "w") as f:
            json.dump({
                "thread_slug": thread_slug,
                "thread_url": thread_url,
                "captured_requests": parsed_requests,
                "summary": {
                    "total_requests": len(captured_requests),
                    "query_endpoints": [
                        r["url"] for r in captured_requests 
                        if "/rest/sse/perplexity_ask" in r["url"] or "/api/chat" in r["url"]
                    ],
                },
            }, f, indent=2)
        
        print(f"\nResults saved to: {output_file}")
        
        if captured_requests:
            print("\n" + "=" * 70)
            print("ANALYSIS")
            print("=" * 70)
            for i, req in enumerate(captured_requests, 1):
                print(f"\nRequest {i}:")
                print(f"  URL: {req['url']}")
                if req.get("postDataParsed"):
                    params = req["postDataParsed"].get("params", {})
                    print(f"  Key parameters:")
                    print(f"    - frontend_context_uuid: {params.get('frontend_context_uuid', 'NOT PRESENT')}")
                    print(f"    - context_uuid: {params.get('context_uuid', 'NOT PRESENT')}")
                    print(f"    - read_write_token: {params.get('read_write_token', 'NOT PRESENT')}")
                    print(f"    - is_related_query: {params.get('is_related_query', 'NOT PRESENT')}")
                    print(f"    - thread_url_slug: {params.get('thread_url_slug', 'NOT PRESENT')}")
                    print(f"    - frontend_uuid: {params.get('frontend_uuid', 'NOT PRESENT')}")
        else:
            print("\n⚠ No query requests captured.")
            print("  Make sure you send a follow-up query in the browser during the 60-second window.")
    
    except ConnectionRefusedError:
        print("✗ Cannot connect to Chrome DevTools Protocol")
        print("  Make sure Chrome is running with: --remote-debugging-port=9222")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await client.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_followup_request.py <thread_slug>")
        print("\nExample:")
        print("  python scripts/inspect_followup_request.py what-is-python-HDn1I22.QKCoDctO58P2UA")
        sys.exit(1)
    
    thread_slug = sys.argv[1]
    asyncio.run(inspect_followup_request(thread_slug))

