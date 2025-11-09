#!/usr/bin/env python3
"""Test direct websocket connection to Chrome DevTools.

This script attempts to connect to Chrome running on port 9222 and
perform the authentication test.
"""

import asyncio
import json
import urllib.request

import pytest
import websockets


@pytest.mark.asyncio
async def test_chrome_connection():
    """Test websocket connection to Chrome DevTools."""
    print("Testing Chrome connection on port 9222...")

    # First, get list of targets from Chrome
    try:
        url = "http://localhost:9222/json"
        with urllib.request.urlopen(url, timeout=5) as response:
            targets = json.loads(response.read())
        print("✓ Connected to Chrome HTTP endpoint")
        print(f"  Found {len(targets)} target(s)")

        for i, target in enumerate(targets):
            print(f"  {i}: {target.get('type')} - {target.get('title', 'Unknown')}")

        # Find a page target
        page_target = next((t for t in targets if t.get("type") == "page"), None)

        if not page_target:
            print("✗ No page target found")
            return False

        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            print("✗ No WebSocket URL available")
            return False

        print("\n✓ Found page target")
        print(f"  WebSocket URL: {ws_url}")

        # Connect via WebSocket
        print("\nConnecting via WebSocket...")
        async with websockets.connect(ws_url) as ws:
            print("✓ WebSocket connected!")

            # Send a simple Page.getVersion command
            command = {
                "id": 1,
                "method": "Browser.getVersion",
            }

            await ws.send(json.dumps(command))
            response = await ws.recv()
            data = json.loads(response)

            print("✓ Received response from Chrome")
            print(f"  Response: {json.dumps(data, indent=2)}")

            if "result" in data:
                version_info = data["result"]
                print(f"\n✓ Chrome Version: {version_info.get('product', 'Unknown')}")

            return True

    except urllib.error.URLError as e:
        print(f"✗ Failed to connect to Chrome HTTP endpoint: {e}")
        print("\nMake sure Chrome is running with:")
        print(
            "  /Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=9222"
        )
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_chrome_connection())
    exit(0 if result else 1)
