#!/usr/bin/env python3
"""Research the follow-up issue by capturing browser behavior.

This script will:
1. Navigate to a specific thread page
2. Capture the exact request when sending a follow-up
3. Analyze what fields are used to link the follow-up to the thread
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import websockets
from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient


async def research_followup():
    """Research follow-up request behavior."""
    print("=" * 70)
    print("RESEARCHING FOLLOW-UP REQUEST BEHAVIOR")
    print("=" * 70)
    print()
    print("This script will:")
    print("1. Connect to Chrome DevTools")
    print("2. Navigate to a thread page")
    print("3. Monitor network requests")
    print("4. Capture the exact payload when you send a follow-up")
    print()
    
    client = ChromeDevToolsClient(port=9222)
    
    try:
        print("Connecting to Chrome...")
        await client.connect()
        print("✓ Connected")
        
        # Enable Network domain
        await client.send_command("Network.enable", {
            "maxResourceBufferSize": 1024 * 1024,
            "maxPostDataSize": 1024 * 1024
        })
        print("✓ Network monitoring enabled")
        
        # Enable Page domain
        await client.send_command("Page.enable")
        print("✓ Page domain enabled")
        
        # Get thread slug from user or use a test one
        if len(sys.argv) > 1:
            thread_slug = sys.argv[1]
        else:
            print("\nPlease provide a thread slug:")
            print("Usage: python scripts/research_followup_issue.py <thread_slug>")
            print("\nExample:")
            print("  python scripts/research_followup_issue.py what-is-the-capital-of-france-NYD1FemPRVaK6F8KT.sbFA")
            await client.close()
            return
        
        thread_url = f"https://www.perplexity.ai/thread/{thread_slug}"
        print(f"\nNavigating to: {thread_url}")
        await client.send_command("Page.navigate", {"url": thread_url})
        
        print("Waiting for page to load...")
        await asyncio.sleep(8)
        
        # Check page state
        try:
            result = await client.send_command("Runtime.evaluate", {
                "expression": "document.readyState"
            })
            ready_state = result.get("result", {}).get("value", "unknown")
            print(f"Page ready state: {ready_state}")
        except Exception as e:
            print(f"Could not check page state: {e}")
        
        # Try to extract thread context from page
        print("\nExtracting thread context from page...")
        try:
            # Try to get context from localStorage or window
            context_result = await client.send_command("Runtime.evaluate", {
                "expression": """
                (function() {
                    try {
                        // Check localStorage for session data
                        const session = localStorage.getItem('pplx-next-auth-session');
                        if (session) {
                            return {hasSession: true, sessionLength: session.length};
                        }
                        return {hasSession: false};
                    } catch(e) {
                        return {error: e.message};
                    }
                })()
                """
            })
            context_data = context_result.get("result", {}).get("value", {})
            print(f"Session data: {context_data}")
        except Exception as e:
            print(f"Could not extract context: {e}")
        
        # Set up request capture
        captured_requests = []
        request_ids = {}
        
        print("\n" + "=" * 70)
        print("MONITORING NETWORK REQUESTS")
        print("=" * 70)
        print("Please send a follow-up query in the browser now.")
        print("The script will capture the exact request payload.")
        print("Waiting 120 seconds...")
        print("-" * 70)
        
        start_time = asyncio.get_event_loop().time()
        timeout = 120.0
        
        async def message_handler():
            while True:
                try:
                    message = await client.ws.recv()
                    data = json.loads(message)
                    
                    if "id" in data and "method" not in data:
                        continue
                    
                    if "method" in data:
                        method = data["method"]
                        params = data.get("params", {})
                        
                        if method == "Network.requestWillBeSent":
                            request = params.get("request", {})
                            request_id = params.get("requestId")
                            url = request.get("url", "")
                            
                            # Look for query API endpoint
                            if "/rest/sse/perplexity_ask" in url:
                                post_data = request.get("postData", "")
                                
                                elapsed = asyncio.get_event_loop().time() - start_time
                                
                                request_info = {
                                    "requestId": request_id,
                                    "url": url,
                                    "method": request.get("method", ""),
                                    "postData": post_data,
                                    "timestamp": elapsed,
                                }
                                
                                request_ids[request_id] = request_info
                                captured_requests.append(request_info)
                                
                                print(f"\n{'='*70}")
                                print(f"✓ CAPTURED FOLLOW-UP REQUEST at {elapsed:.1f}s")
                                print(f"{'='*70}")
                                
                                if post_data:
                                    try:
                                        post_json = json.loads(post_data)
                                        params_dict = post_json.get("params", {})
                                        
                                        print(f"\nURL: {url}")
                                        print(f"\nKEY FIELDS:")
                                        key_fields = {
                                            "frontend_uuid": params_dict.get("frontend_uuid"),
                                            "frontend_context_uuid": params_dict.get("frontend_context_uuid"),
                                            "context_uuid": params_dict.get("context_uuid"),
                                            "read_write_token": params_dict.get("read_write_token"),
                                            "thread_url_slug": params_dict.get("thread_url_slug"),
                                            "is_related_query": params_dict.get("is_related_query"),
                                        }
                                        for k, v in key_fields.items():
                                            if v is not None:
                                                print(f"  ✓ {k}: {v}")
                                            else:
                                                print(f"  ✗ {k}: NOT PRESENT")
                                        
                                        print(f"\nQuery: {post_json.get('query_str', '')}")
                                        
                                        # Save full request
                                        output_file = Path(__file__).parent.parent / "docs" / "browser_followup_research.json"
                                        output_file.parent.mkdir(exist_ok=True)
                                        with open(output_file, "w") as f:
                                            json.dump({
                                                "thread_slug": thread_slug,
                                                "thread_url": thread_url,
                                                "request": post_json,
                                                "key_fields": key_fields,
                                            }, f, indent=2)
                                        print(f"\n✓ Full request saved to: {output_file}")
                                        
                                    except json.JSONDecodeError as e:
                                        print(f"JSON parse error: {e}")
                                        print(f"Post data (first 500 chars): {post_data[:500]}")
                        
                        elif method == "Network.responseReceived":
                            request_id = params.get("requestId")
                            if request_id in request_ids:
                                response = params.get("response", {})
                                request_ids[request_id]["responseStatus"] = response.get("status")
                
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception as e:
                    print(f"Error: {e}")
                    continue
        
        try:
            await asyncio.wait_for(message_handler(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        
        print(f"\n✓ Monitoring complete. Captured {len(captured_requests)} requests")
        
        if not captured_requests:
            print("\n⚠ No follow-up requests captured.")
            print("  Make sure you send a follow-up query in the browser during the monitoring window.")
    
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
    asyncio.run(research_followup())

