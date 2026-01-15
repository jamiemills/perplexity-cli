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
    timeout: int = 120,
    poll_interval: float = 2.0,
) -> tuple[str, dict[str, str]]:
    """Authenticate with Perplexity via Google and extract the session token and cookies.

    Opens Chrome to the Perplexity login page and monitors network traffic
    to capture the authentication token from localStorage and all browser cookies
    (including Cloudflare cookies for bot detection bypass).

    Args:
        url: The Perplexity URL to navigate to. If None, uses configured base URL.
        port: The Chrome remote debugging port (default: 9222).
        timeout: Maximum time to wait for authentication in seconds (default: 120).
        poll_interval: Time between polling attempts in seconds (default: 2.0).

    Returns:
        Tuple of (token, cookies_dict) where:
            - token: The extracted authentication token
            - cookies_dict: Dictionary of all browser cookies {name: value}

    Raises:
        RuntimeError: If Chrome is not available or authentication fails.
        TimeoutError: If authentication timeout is exceeded.
    """
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()

    if url is None:
        url = get_perplexity_base_url()

    client = ChromeDevToolsClient(port)

    try:
        logger.info(f"Connecting to Chrome on port {port}...")
        await client.connect()
        logger.info("Connected to Chrome")

        # Enable the Page domain
        await client.send_command("Page.enable")

        # Enable the Network domain to capture cookies
        await client.send_command("Network.enable")

        # Navigate to the URL
        logger.info(f"Navigating to {url}...")
        navigate_result = await client.send_command("Page.navigate", {"url": url})
        logger.debug(f"Navigation result: {navigate_result}")

        # Wait for page load using polling
        logger.debug("Waiting for page to load...")
        await _wait_for_page_load(client, timeout=30)

        # Poll for authentication token with timeout
        logger.info("Waiting for authentication...")
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise TimeoutError(
                    f"Authentication timeout after {timeout} seconds. "
                    "Please ensure you have logged in to Perplexity.ai in Chrome."
                )

            # Get all cookies
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

            # Extract session token and cookies
            session_token, cookie_dict = _extract_token(cookies, local_storage_data)

            if session_token:
                logger.info(
                    f"Successfully extracted authentication token and {len(cookie_dict)} cookies"
                )
                return (session_token, cookie_dict)

            # Wait before next poll
            logger.debug(
                f"No token found yet, waiting {poll_interval}s... (elapsed: {elapsed:.1f}s)"
            )
            await asyncio.sleep(poll_interval)

    finally:
        await client.close()


async def _wait_for_page_load(client: ChromeDevToolsClient, timeout: int = 30) -> None:
    """Wait for page to finish loading.

    Args:
        client: Chrome DevTools client instance.
        timeout: Maximum time to wait in seconds.

    Raises:
        TimeoutError: If page doesn't load within timeout.
    """
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    start_time = asyncio.get_event_loop().time()
    poll_interval = 0.5

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Page load timeout after {timeout} seconds")

        try:
            # Check if page is loaded
            result = await client.send_command("Page.getNavigationHistory")
            if result:
                logger.debug("Page loaded successfully")
                return
        except Exception as e:
            logger.debug(f"Page not ready yet: {e}")

        await asyncio.sleep(poll_interval)


def _extract_token(
    cookies: list[dict[str, Any]], local_storage: dict[str, str]
) -> tuple[str | None, dict[str, str]]:
    """Extract authentication token and cookies from browser.

    Args:
        cookies: List of cookie dictionaries from Chrome.
        local_storage: Dictionary of localStorage key-value pairs.

    Returns:
        Tuple of (token, cookies_dict) where:
            - token: The authentication token string, or None if not found
            - cookies_dict: Dictionary of all cookies {name: value}
    """
    # Build complete cookie dictionary from all browser cookies
    cookie_dict = {c["name"]: c["value"] for c in cookies}

    # Try to extract token from localStorage session data
    token = None
    if "pplx-next-auth-session" in local_storage:
        try:
            session_data = json.loads(local_storage["pplx-next-auth-session"])
            # Perplexity stores session as NextAuth.js session
            # Return the entire session data as token
            token = json.dumps(session_data)
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to extract token from cookies (fallback)
    if not token:
        for cookie_name in ["__Secure-next-auth.session-token", "next-auth.session-token"]:
            if cookie_name in cookie_dict:
                token = cookie_dict[cookie_name]
                break

    return (token, cookie_dict)


def authenticate_sync(
    url: str | None = None,
    port: int = 9222,
    timeout: int = 120,
    poll_interval: float = 2.0,
) -> tuple[str, dict[str, str]]:
    """Synchronous wrapper for authenticate_with_browser.

    Args:
        url: The Perplexity URL to navigate to. If None, uses configured base URL.
        port: The Chrome remote debugging port.
        timeout: Maximum time to wait for authentication in seconds (default: 120).
        poll_interval: Time between polling attempts in seconds (default: 2.0).

    Returns:
        Tuple of (token, cookies_dict) where:
            - token: The extracted authentication token
            - cookies_dict: Dictionary of all browser cookies {name: value}

    Raises:
        RuntimeError: If Chrome is not available or authentication fails.
        TimeoutError: If authentication timeout is exceeded.
    """
    return asyncio.run(authenticate_with_browser(url, port, timeout, poll_interval))
