"""OAuth authentication handler using Chrome DevTools Protocol.

This module handles the authentication flow with Perplexity.ai using browser
automation. It opens the browser to Perplexity's login page and captures the
authentication token via Chrome's DevTools Protocol.
"""

import asyncio
import json
from typing import Any

import websockets

from ..utils.config import get_perplexity_base_url


class ChromeDevToolsClient:
    """Client for communicating with Chrome via DevTools Protocol."""

    def __init__(self, port: int) -> None:
        """Initialise Chrome DevTools client.

        Args:
            port: The Chrome remote debugging port.
        """
        self.port = port
        self.ws: Any | None = None
        self.message_id = 0

    async def connect(self) -> None:
        """Connect to Chrome's remote debugging endpoint.

        Raises:
            RuntimeError: If Chrome is not running or endpoint is unavailable.
        """
        import json as json_module
        import urllib.request

        url = f"http://localhost:{self.port}/json"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                targets = json_module.loads(response.read())
        except Exception as e:
            raise RuntimeError(
                f"Failed to connect to Chrome on port {self.port}. "
                f"Ensure Chrome is running with --remote-debugging-port={self.port}. "
                f"Error: {e}"
            ) from e

        # Find a page target
        page_target = next((t for t in targets if t.get("type") == "page"), None)

        if not page_target:
            raise RuntimeError("No page target found in Chrome")

        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("Could not get WebSocket debugger URL")

        self.ws = await websockets.connect(ws_url)

    async def send_command(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a command to Chrome and wait for the response.

        Args:
            method: The Chrome DevTools Protocol method name.
            params: Optional parameters for the method.

        Returns:
            The result from Chrome.

        Raises:
            RuntimeError: If not connected or Chrome returns an error.
        """
        if not self.ws:
            raise RuntimeError("Not connected to Chrome")

        self.message_id += 1
        command: dict[str, Any] = {
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


async def authenticate_with_browser(
    url: str | None = None,
    port: int = 9222,
) -> str:
    """Authenticate with Perplexity via Google and extract the session token.

    Opens Chrome to the Perplexity login page and monitors network traffic
    to capture the authentication token from localStorage.

    Args:
        url: The Perplexity URL to navigate to. If None, uses configured base URL.
        port: The Chrome remote debugging port (default: 9222).

    Returns:
        The extracted authentication token.

    Raises:
        RuntimeError: If Chrome is not available or authentication fails.
    """
    if url is None:
        url = get_perplexity_base_url()

    client = ChromeDevToolsClient(port)

    try:
        print(f"Connecting to Chrome on port {port}...")
        await client.connect()
        print("Connected to Chrome!")

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
        print("Extracting authentication data...")
        cookies_result = await client.send_command("Network.getAllCookies")
        cookies = cookies_result.get("cookies", [])

        # Get localStorage data
        local_storage_result = await client.send_command(
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
            },
        )

        local_storage_data: dict[str, Any] = {}
        if "result" in local_storage_result and "value" in local_storage_result["result"]:
            local_storage_data = local_storage_result["result"]["value"]

        # Extract session token from localStorage
        session_token = _extract_token(cookies, local_storage_data)

        if not session_token:
            raise RuntimeError(
                "Failed to extract authentication token. "
                "Ensure you have logged in to Perplexity.ai."
            )

        print("Successfully extracted authentication token")
        return session_token

    finally:
        await client.close()


def _extract_token(cookies: list[dict[str, Any]], local_storage: dict[str, str]) -> str | None:
    """Extract authentication token from cookies and localStorage.

    Args:
        cookies: List of cookie dictionaries.
        local_storage: Dictionary of localStorage key-value pairs.

    Returns:
        The authentication token string, or None if not found.
    """
    # Try to extract from localStorage session data
    if "pplx-next-auth-session" in local_storage:
        try:
            session_data = json.loads(local_storage["pplx-next-auth-session"])
            # Perplexity stores session as NextAuth.js session
            # Return the entire session data as token
            return json.dumps(session_data)
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to extract from cookies (fallback)
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    # Common authentication cookie names
    for cookie_name in ["__Secure-next-auth.session-token", "next-auth.session-token"]:
        if cookie_name in cookie_dict:
            return cookie_dict[cookie_name]

    return None


def authenticate_sync(
    url: str | None = None,
    port: int = 9222,
) -> str:
    """Synchronous wrapper for authenticate_with_browser.

    Args:
        url: The Perplexity URL to navigate to. If None, uses configured base URL.
        port: The Chrome remote debugging port.

    Returns:
        The extracted authentication token.

    Raises:
        RuntimeError: If Chrome is not available or authentication fails.
    """
    return asyncio.run(authenticate_with_browser(url, port))
