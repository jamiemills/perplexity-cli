#!/usr/bin/env python3
"""
Authenticate with Perplexity.ai via Google and extract session cookies.

Connects to a running Chrome instance via remote debugging protocol.
Usage: python authenticate.py --url https://www.perplexity.ai --port 9222
"""

import argparse
import json
import asyncio
import websockets
from typing import Any, Dict, List


class ChromeDevToolsClient:
    """Client for communicating with Chrome via DevTools Protocol."""

    def __init__(self, port: int):
        self.port = port
        self.ws = None
        self.message_id = 0

    async def connect(self) -> None:
        """Connect to Chrome's remote debugging endpoint."""
        # Get the list of available targets
        import urllib.request
        import json as json_module

        url = f"http://localhost:{self.port}/json"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                targets = json_module.loads(response.read())
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Chrome on port {self.port}. "
                f"Ensure Chrome is running with --remote-debugging-port={self.port}. "
                f"Error: {e}"
            )

        # Find a page target
        page_target = next(
            (t for t in targets if t.get("type") == "page"),
            None
        )

        if not page_target:
            raise RuntimeError("No page target found in Chrome")

        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Could not get WebSocket debugger URL")

        self.ws = await websockets.connect(ws_url)

    async def send_command(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Chrome and wait for the response."""
        if not self.ws:
            raise RuntimeError("Not connected to Chrome")

        self.message_id += 1
        command = {
            "id": self.message_id,
            "method": method,
        }
        if params:
            command["params"] = params

        await self.ws.send(json.dumps(command))

        # Wait for the response
        while True:
            response = await self.ws.recv()
            data = json.loads(response)

            if data.get("id") == self.message_id:
                if "error" in data:
                    raise RuntimeError(f"Chrome error: {data['error']}")
                return data.get("result", {})

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()


async def authenticate_via_google(url: str, port: int, output_file: str) -> None:
    """
    Connect to Chrome, navigate to URL, and extract authentication data.
    """
    client = ChromeDevToolsClient(port)

    try:
        print(f"Connecting to Chrome on port {port}...")
        await client.connect()
        print("Connected!")

        # Enable the Page domain
        await client.send_command("Page.enable")

        # Enable the Network domain to capture cookies
        await client.send_command("Network.enable")

        # Navigate to the URL
        print(f"Navigating to {url}...")
        await client.send_command("Page.navigate", {"url": url})

        # Wait for the page to load
        await asyncio.sleep(3)

        # Get all cookies
        print("Extracting cookies...")
        cookies_result = await client.send_command("Network.getAllCookies")
        cookies = cookies_result.get("cookies", [])

        # Build cookie string
        cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        # Get localStorage data
        print("Extracting localStorage...")
        local_storage = await client.send_command(
            "Runtime.evaluate",
            {
                "expression": """
                    (() => {
                        const storage = {};
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            storage[key] = localStorage.getItem(key);
                        }
                        return storage;
                    })()
                """
            }
        )

        local_storage_data = {}
        if "result" in local_storage and "value" in local_storage["result"]:
            local_storage_data = local_storage["result"]["value"]

        # Extract session data from localStorage
        session_data = None
        if "pplx-next-auth-session" in local_storage_data:
            try:
                session_data = json.loads(local_storage_data["pplx-next-auth-session"])
            except (json.JSONDecodeError, TypeError):
                pass

        # Prepare auth data
        auth_data = {
            "cookies": cookie_string,
            "cookie_dict": {c['name']: c['value'] for c in cookies},
            "session": session_data,
            "localStorage": {
                "pplx-next-auth-session": local_storage_data.get("pplx-next-auth-session"),
                "user_id": local_storage_data.get("perplexity_ai_039eb8fb_ai.perplexity_singular_custom_user_id")
            },
            "note": "For API calls, include the cookies string in your HTTP request headers as 'Cookie: <cookies>'."
        }

        # Save to file
        with open(output_file, "w") as f:
            json.dump(auth_data, f, indent=2)

        print(f"\nAuthentication data saved to {output_file}")
        if session_data:
            print(f"User: {session_data.get('user', {}).get('email', 'Unknown')}")
            print(f"Session expires: {session_data.get('expires', 'Unknown')}")

    finally:
        await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Connect to Chrome and extract session cookies from a website."
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="The website URL to navigate to"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9222,
        help="Chrome remote debugging port (default: 9222)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=".perplexity-auth.json",
        help="Output file for authentication data (default: .perplexity-auth.json)"
    )
    args = parser.parse_args()

    asyncio.run(authenticate_via_google(args.url, args.port, args.output))
