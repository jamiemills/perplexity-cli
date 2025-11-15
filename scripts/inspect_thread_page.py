#!/usr/bin/env python3
"""Inspect thread page structure and API calls using CDP.

This script navigates to a thread page and captures:
1. DOM structure (query/message elements)
2. Network requests (especially thread detail endpoints)
3. Page data (React state, window objects)
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
from perplexity_cli.auth.oauth_handler import ChromeDevToolsClient


async def inspect_thread_page(thread_hash: str):
    """Inspect a thread page using CDP."""
    print("=" * 70)
    print(f"INSPECTING THREAD PAGE: {thread_hash}")
    print("=" * 70)
    
    # Get thread info from API
    tm = TokenManager()
    token = tm.load_token()
    if not token:
        print("✗ Not authenticated")
        return None
    
    api = PerplexityAPI(token=token)
    thread = find_thread_by_identifier(api, thread_hash)
    
    if not thread:
        print(f"✗ Thread not found: {thread_hash}")
        return None
    
    print(f"\nThread Info from API:")
    print(f"  Slug: {thread.slug}")
    print(f"  Title: {thread.title}")
    print(f"  query_count (API): {thread.query_count}")
    print(f"  frontend_context_uuid: {thread.frontend_context_uuid}")
    
    client = ChromeDevToolsClient(port=9222)
    
    try:
        # Connect and create a page if needed
        import httpx
        debug_url = "http://localhost:9222"
        response = httpx.get(f"{debug_url}/json/new", timeout=5)
        if response.status_code == 200:
            page_info = response.json()
            ws_url = page_info.get("webSocketDebuggerUrl")
            if ws_url:
                # Use the new page's websocket URL
                client.ws_url = ws_url
                await client.connect()
                print("\n✓ Connected to Chrome (created new page)")
            else:
                await client.connect()
                print("\n✓ Connected to Chrome")
        else:
            await client.connect()
            print("\n✓ Connected to Chrome")
        
        await client.send_command("Page.enable")
        await client.send_command("Runtime.enable")
        await client.send_command("Network.enable", {
            "maxResourceBufferSize": 1024 * 1024,
            "maxPostDataSize": 1024 * 1024
        })
        
        # Try both URL formats - /thread/ and /search/
        thread_url = f"https://www.perplexity.ai/search/{thread.slug}"
        print(f"\nNavigating to: {thread_url}")
        await client.send_command("Page.navigate", {"url": thread_url})
        
        print("Waiting for page to load...")
        await asyncio.sleep(8)
        
        # Extract thread structure from page
        print("\nExtracting thread structure...")
        
        extract_script = """
        (function() {
            const data = {
                url: window.location.href,
                threadSlug: window.location.pathname.split('/').pop(),
                queries: [],
                messages: [],
            };
            
            // Try multiple selectors to find query/message elements
            const selectors = [
                '[data-query-id]',
                '[class*="Query"]',
                '[class*="query"]',
                '[class*="Message"]',
                '[class*="message"]',
                '[class*="ThreadItem"]',
                '[class*="thread-item"]',
                'article',
                '[role="article"]',
            ];
            
            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                if (elements.length > 0) {
                    data[selector.replace(/[^a-zA-Z0-9]/g, '_')] = elements.length;
                }
            }
            
            // Look for thread data in window
            if (window.__NEXT_DATA__) {
                const nextData = window.__NEXT_DATA__.props;
                if (nextData && nextData.pageProps) {
                    data.nextDataPageProps = Object.keys(nextData.pageProps);
                }
            }
            
            // Try to find thread structure
            const threadContainer = document.querySelector('[class*="thread"], [id*="thread"], main, [role="main"]');
            if (threadContainer) {
                const children = threadContainer.children;
                data.containerChildren = children.length;
                
                // Look for query/message indicators
                for (let i = 0; i < Math.min(children.length, 10); i++) {
                    const child = children[i];
                    const text = child.textContent || '';
                    if (text.length > 0 && text.length < 200) {
                        data.messages.push({
                            index: i,
                            preview: text.substring(0, 100),
                            classes: Array.from(child.classList || []),
                        });
                    }
                }
            }
            
            return data;
        })()
        """
        
        result = await client.send_command("Runtime.evaluate", {
            "expression": extract_script,
            "returnByValue": True
        })
        
        page_data = result.get("result", {}).get("value", {})
        print(f"\nPage structure extracted:")
        print(json.dumps(page_data, indent=2))
        
        # Monitor network requests
        print("\n" + "=" * 70)
        print("CAPTURING NETWORK REQUESTS")
        print("=" * 70)
        print("Monitoring for 20 seconds...")
        
        captured_requests = []
        request_ids = {}
        start_time = asyncio.get_event_loop().time()
        timeout = 20.0
        
        async def message_handler():
            while True:
                try:
                    message = await asyncio.wait_for(client.ws.recv(), timeout=1.0)
                    data = json.loads(message)
                    
                    if "method" in data:
                        method = data["method"]
                        params = data.get("params", {})
                        
                        if method == "Network.requestWillBeSent":
                            request = params.get("request", {})
                            request_id = params.get("requestId")
                            url = request.get("url", "")
                            
                            # Capture thread-related requests
                            if any(keyword in url.lower() for keyword in ["thread", "query", "message", "conversation", "/rest/"]):
                                req_info = {
                                    "requestId": request_id,
                                    "url": url,
                                    "method": request.get("method"),
                                    "headers": {k: v for k, v in request.get("headers", {}).items() if k.lower() not in ["authorization", "cookie"]},
                                }
                                
                                if request.get("postData"):
                                    try:
                                        req_info["postData"] = json.loads(request.get("postData"))
                                    except:
                                        req_info["postData"] = request.get("postData")[:200]
                                
                                captured_requests.append(req_info)
                                request_ids[request_id] = req_info
                                print(f"\n✓ {request.get('method')} {url}")
                        
                        elif method == "Network.responseReceived":
                            request_id = params.get("requestId")
                            if request_id in request_ids:
                                response = params.get("response", {})
                                request_ids[request_id]["status"] = response.get("status")
                                request_ids[request_id]["responseUrl"] = response.get("url")
                    
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break
                except Exception:
                    continue
        
        try:
            await asyncio.wait_for(message_handler(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        
        print(f"\n✓ Captured {len(captured_requests)} requests")
        
        # Save results
        output_file = Path(__file__).parent.parent / "docs" / f"thread_inspection_{thread_hash}.json"
        output_file.parent.mkdir(exist_ok=True)
        
        results = {
            "thread_hash": thread_hash,
            "thread_slug": thread.slug,
            "api_thread_info": {
                "title": thread.title,
                "query_count": thread.query_count,
                "frontend_context_uuid": thread.frontend_context_uuid,
                "context_uuid": thread.context_uuid,
            },
            "page_data": page_data,
            "captured_requests": captured_requests,
        }
        
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\n✓ Results saved to: {output_file}")
        
        await client.close()
        return results
        
    except ConnectionRefusedError:
        print("✗ Cannot connect to Chrome DevTools")
        print("  Make sure Chrome is running with: --remote-debugging-port=9222")
        return None
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    threads = ["1e8ef0ac", "1f344d10", "b4cf5f8d"]
    all_results = {}
    
    for thread_hash in threads:
        result = await inspect_thread_page(thread_hash)
        if result:
            all_results[thread_hash] = result
        print("\n" + "=" * 70 + "\n")
        await asyncio.sleep(2)
    
    # Save combined results
    combined_file = Path(__file__).parent.parent / "docs" / "thread_inspection_combined.json"
    with open(combined_file, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"✓ Combined results saved to: {combined_file}")


if __name__ == "__main__":
    asyncio.run(main())

