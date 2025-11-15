#!/usr/bin/env python3
"""Inspect the library page to discover API endpoints.

Uses Chrome DevTools Protocol to navigate to the library page and capture
network requests to discover the actual API endpoints.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient
from perplexity_cli.auth.token_manager import TokenManager


async def inspect_library_page():
    """Use Chrome DevTools Protocol to inspect library page API calls."""
    # Check authentication
    tm = TokenManager()
    token = tm.load_token()
    
    if not token:
        print("✗ Not authenticated. Please run: perplexity-cli auth")
        sys.exit(1)

    print("=" * 70)
    print("Inspecting Library Page API Calls")
    print("=" * 70)
    print()

    client = ChromeDevToolsClient(port=9222)
    
    try:
        print("Connecting to Chrome...")
        await client.connect()
        print("✓ Connected to Chrome")
        
        # Enable Network domain
        await client.send_command("Network.enable")
        print("✓ Network domain enabled")
        
        # Enable Page domain
        await client.send_command("Page.enable")
        print("✓ Page domain enabled")
        
        # Navigate to library page
        print("\nNavigating to library page...")
        await client.send_command("Page.navigate", {
            "url": "https://www.perplexity.ai/library"
        })
        
        # Wait for page to load
        print("Waiting for page to load...")
        await asyncio.sleep(5)
        
        # Collect network requests
        api_requests = []
        print("\nCollecting network requests (waiting 15 seconds)...")
        
        # Set up message handler
        message_id = 1000
        
        async def collect_requests():
            nonlocal message_id
            start_time = asyncio.get_event_loop().time()
            
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > 15.0:
                    break
                
                try:
                    # Send a command to keep connection alive and check for messages
                    message_id += 1
                    await client.ws.send(json.dumps({
                        "id": message_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "document.readyState"}
                    }))
                    
                    # Try to receive messages
                    try:
                        message = await asyncio.wait_for(client.ws.recv(), timeout=0.5)
                        data = json.loads(message)
                        
                        # Check for network requests
                        if "method" in data:
                            if data["method"] == "Network.requestWillBeSent":
                                request = data.get("params", {}).get("request", {})
                                url = request.get("url", "")
                                
                                # Filter for API endpoints
                                if any(x in url for x in ["/api/", "/rest/", "library", "thread", "conversation"]):
                                    api_requests.append({
                                        "url": url,
                                        "method": request.get("method", ""),
                                        "headers": request.get("headers", {}),
                                        "postData": request.get("postData"),
                                    })
                                    print(f"  Found: {request.get('method', 'GET')} {url}")
                            
                            elif data["method"] == "Network.responseReceived":
                                response = data.get("params", {}).get("response", {})
                                url = response.get("url", "")
                                
                                if any(x in url for x in ["/api/", "/rest/", "library", "thread", "conversation"]):
                                    print(f"  Response: {response.get('status')} {url}")
                        
                        # Skip response messages for our keepalive commands
                        elif data.get("id") == message_id:
                            pass
                    
                    except asyncio.TimeoutError:
                        continue
                
                except Exception as e:
                    # Continue collecting despite errors
                    continue
        
        await collect_requests()
        
        print(f"\n✓ Collected {len(api_requests)} API requests")
        
        # Also try to get response bodies for successful requests
        if api_requests:
            print("\nFetching response bodies...")
            for i, req in enumerate(api_requests[:5]):  # Limit to first 5
                try:
                    # We'd need requestId from Network.requestWillBeSent to get response body
                    # For now, just log what we have
                    pass
                except Exception:
                    pass
        
        # Save results
        output_file = Path(__file__).parent.parent / "docs" / "library_page_api_calls.json"
        output_file.parent.mkdir(exist_ok=True)
        with open(output_file, "w") as f:
            json.dump({
                "page": "https://www.perplexity.ai/library",
                "api_requests": api_requests,
            }, f, indent=2)
        
        print(f"\nResults saved to: {output_file}")
        
        if api_requests:
            print("\n✓ Discovered API endpoints:")
            for req in api_requests:
                print(f"  {req['method']} {req['url']}")
        else:
            print("\n⚠ No API endpoints found.")
            print("  The page may require authentication or the endpoints may be loaded differently.")
            print("  Try manually navigating to https://www.perplexity.ai/library in Chrome")
            print("  and check the Network tab in DevTools.")
    
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
    asyncio.run(inspect_library_page())

