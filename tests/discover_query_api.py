#!/usr/bin/env python3
"""Discover Perplexity's query API by monitoring network traffic.

This script connects to Chrome DevTools and monitors network requests
while you submit a query on Perplexity.ai to discover the actual API endpoints.
"""

import asyncio
import json
import urllib.request

import websockets


class NetworkMonitor:
    """Monitor network traffic via Chrome DevTools Protocol."""

    def __init__(self, port: int = 9222):
        """Initialise network monitor.

        Args:
            port: Chrome remote debugging port.
        """
        self.port = port
        self.ws = None
        self.message_id = 0
        self.requests_captured = []

    async def connect(self):
        """Connect to Chrome's remote debugging endpoint."""
        url = f"http://localhost:{self.port}/json"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                targets = json.loads(response.read())
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Chrome on port {self.port}. "
                f"Ensure Chrome is running with --remote-debugging-port={self.port}. "
                f"Error: {e}"
            ) from e

        page_target = next((t for t in targets if t.get("type") == "page"), None)
        if not page_target:
            raise RuntimeError("No page target found in Chrome")

        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Could not get WebSocket debugger URL")

        self.ws = await websockets.connect(ws_url)

    async def send_command(self, method: str, params: dict | None = None):
        """Send a command to Chrome.

        Args:
            method: The Chrome DevTools Protocol method.
            params: Optional parameters.

        Returns:
            The command result.
        """
        if not self.ws:
            raise RuntimeError("Not connected to Chrome")

        self.message_id += 1
        command = {"id": self.message_id, "method": method}
        if params:
            command["params"] = params

        await self.ws.send(json.dumps(command))

        while True:
            response = await self.ws.recv()
            data = json.loads(response)

            if data.get("id") == self.message_id:
                if "error" in data:
                    raise RuntimeError(f"Chrome error: {data['error']}")
                return data.get("result", {})

            # Capture network events
            if data.get("method") == "Network.requestWillBeSent":
                await self._handle_request(data.get("params", {}))
            elif data.get("method") == "Network.responseReceived":
                await self._handle_response(data.get("params", {}))

    async def _handle_request(self, params: dict):
        """Handle network request event."""
        request_info = params.get("request", {})
        url = request_info.get("url", "")

        # Only capture Perplexity API calls
        if "perplexity.ai" in url and "/api/" in url:
            request_id = params.get("requestId")
            self.requests_captured.append(
                {
                    "requestId": request_id,
                    "url": url,
                    "method": request_info.get("method"),
                    "headers": request_info.get("headers", {}),
                    "postData": request_info.get("postData"),
                    "type": "request",
                }
            )
            print("\n📡 Captured Request:")
            print(f"   URL: {url}")
            print(f"   Method: {request_info.get('method')}")
            if request_info.get("postData"):
                print(f"   POST Data: {request_info.get('postData')[:200]}...")

    async def _handle_response(self, params: dict):
        """Handle network response event."""
        response_info = params.get("response", {})
        url = response_info.get("url", "")

        if "perplexity.ai" in url and "/api/" in url:
            print("\n📥 Captured Response:")
            print(f"   URL: {url}")
            print(f"   Status: {response_info.get('status')}")
            print(f"   Type: {response_info.get('mimeType')}")

    async def monitor(self, duration: int = 60):
        """Monitor network traffic for a specified duration.

        Args:
            duration: How long to monitor in seconds.
        """
        print(f"Connecting to Chrome on port {self.port}...")
        await self.connect()
        print("✓ Connected to Chrome!\n")

        # Enable Network domain
        await self.send_command("Network.enable")
        print("✓ Network monitoring enabled\n")

        print("=" * 70)
        print("MONITORING NETWORK TRAFFIC")
        print("=" * 70)
        print(f"\nNow monitoring for {duration} seconds...")
        print("Go to Perplexity.ai in your Chrome browser and submit a query.\n")
        print("Watching for API calls...\n")

        # Listen for network events
        try:
            async with asyncio.timeout(duration):
                while True:
                    response = await self.ws.recv()
                    data = json.loads(response)

                    # Handle network events
                    if data.get("method") == "Network.requestWillBeSent":
                        await self._handle_request(data.get("params", {}))
                    elif data.get("method") == "Network.responseReceived":
                        await self._handle_response(data.get("params", {}))

        except TimeoutError:
            print("\n\n" + "=" * 70)
            print("MONITORING COMPLETE")
            print("=" * 70)

        finally:
            if self.ws:
                await self.ws.close()

        return self.requests_captured

    async def close(self):
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()


async def discover_query_api():
    """Discover the Perplexity query API by monitoring network traffic."""
    monitor = NetworkMonitor(port=9222)

    try:
        requests = await monitor.monitor(duration=60)

        if not requests:
            print("\n⚠️  No API calls captured.")
            print("Make sure you submitted a query on Perplexity.ai during monitoring.")
            return

        print(f"\n\n✓ Captured {len(requests)} API request(s)\n")
        print("=" * 70)
        print("API ENDPOINT DETAILS")
        print("=" * 70 + "\n")

        for i, req in enumerate(requests, 1):
            print(f"Request {i}:")
            print(f"  URL: {req['url']}")
            print(f"  Method: {req['method']}")
            print("  Headers:")
            for key, value in list(req.get("headers", {}).items())[:10]:
                if key.lower() not in ["cookie", "authorization"]:
                    print(f"    {key}: {value}")
            if req.get("postData"):
                print(f"  POST Data: {req['postData'][:500]}")
            print()

        # Save to file
        from pathlib import Path

        project_root = Path(__file__).parent.parent
        output_file = project_root / ".claudeCode" / "api_discovery.json"
        with open(output_file, "w") as f:
            json.dump(requests, f, indent=2)

        print(f"✓ Full details saved to: {output_file}\n")

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  PERPLEXITY QUERY API DISCOVERY")
    print("=" * 70 + "\n")
    print("Prerequisites:")
    print("1. Chrome must be running with --remote-debugging-port=9222")
    print("2. Navigate to https://www.perplexity.ai in Chrome")
    print("3. When monitoring starts, submit a query on Perplexity.ai\n")

    input("Press Enter when ready to start monitoring...")

    asyncio.run(discover_query_api())
