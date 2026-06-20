"""OAuth authentication handler using Chrome DevTools Protocol.

This module handles the authentication flow with Perplexity.ai using browser
automation. It opens the browser to Perplexity's login page and captures the
authentication token via Chrome's DevTools Protocol.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from typing import TYPE_CHECKING, Any, TypeGuard, cast

import websockets

from perplexity_cli.utils.async_bridge import run_async
from perplexity_cli.utils.exceptions import AuthenticationError

from ..utils.config import get_perplexity_base_url

if TYPE_CHECKING:
    import logging


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    """TypeGuard: value is a dict with string keys."""
    return isinstance(value, dict)


class ChromeDevToolsClient:
    """Client for communicating with Chrome via DevTools Protocol."""

    def __init__(self, port: int) -> None:
        """Initialise Chrome DevTools client.

        Args:
            port: The Chrome remote debugging port.
        """
        self.port = port
        self.ws: Any | None = None
        self.message_id: int = 0

    async def connect(self) -> None:
        """Connect to Chrome's remote debugging endpoint.

        Raises:
            RuntimeError: If Chrome is not running or endpoint is unavailable.
        """
        targets = self._fetch_targets()
        page_target = self._find_page_target(targets)

        ws_url = page_target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise AuthenticationError("Could not get WebSocket debugger URL")

        self.ws = await websockets.connect(str(ws_url))

    def _fetch_targets(self) -> list[object]:
        """Fetch the list of debugging targets from Chrome.

        Returns:
            List of target dictionaries.

        Raises:
            AuthenticationError: If Chrome is unreachable or returns invalid data.
        """
        url = f"http://localhost:{self.port}/json"
        try:
            # Scheme and host are hardcoded literals; only port varies.
            with urllib.request.urlopen(url, timeout=5) as response:  # nosec B310
                targets = json.loads(response.read())
        except (json.JSONDecodeError, OSError) as e:
            raise AuthenticationError(
                f"Failed to connect to Chrome on port {self.port}. "
                f"Ensure Chrome is running with --remote-debugging-port={self.port}. "
                f"Error: {e}"
            ) from e

        if not isinstance(targets, list):
            raise AuthenticationError("Chrome returned an invalid targets payload")

        return cast(list[object], targets)

    @staticmethod
    def _find_page_target(targets: list[object]) -> dict[str, object]:
        """Find a page-type target from the targets list.

        Args:
            targets: List of Chrome debugging targets.

        Returns:
            The first page target dictionary.

        Raises:
            AuthenticationError: If no page target is found.
        """
        for t in targets:
            if _is_str_dict(t) and t.get("type") == "page":
                return t
        raise AuthenticationError("No page target found in Chrome")

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
            raise AuthenticationError("Not connected to Chrome")

        self.message_id += 1
        command = self._build_command(method, params)
        await self.ws.send(json.dumps(command))
        return await self._await_response()

    def _build_command(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Build a Chrome DevTools Protocol command message.

        Args:
            method: The protocol method name.
            params: Optional parameters for the method.

        Returns:
            The command dictionary ready for serialisation.
        """
        command: dict[str, Any] = {"id": self.message_id, "method": method}
        if params:
            command["params"] = params
        return command

    async def _await_response(self) -> dict[str, Any]:
        """Wait for a response matching the current message ID.

        Returns:
            The result from the matched response.

        Raises:
            AuthenticationError: If Chrome returns an error or not connected.
        """
        if self.ws is None:
            raise AuthenticationError("Not connected to Chrome")
        while True:
            response = await self.ws.recv()
            cdp_message = json.loads(response)
            if cdp_message.get("id") == self.message_id:
                if "error" in cdp_message:
                    raise AuthenticationError(f"Chrome error: {cdp_message['error']}")
                return cdp_message.get("result", {})

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()


def _resolve_auth_defaults(
    url: str | None,
    port: int | None,
    timeout: int | None,
    poll_interval: float | None,
) -> tuple[str, int, int, float]:
    """Resolve default values for authentication parameters.

    Args:
        url: Perplexity URL or None for default.
        port: Chrome debugging port or None for default.
        timeout: Authentication timeout or None for default.
        poll_interval: Polling interval or None for default.

    Returns:
        Tuple of (url, port, timeout, poll_interval) with defaults applied.
    """
    from perplexity_cli.config.defaults import (
        DEFAULT_AUTH_POLL_INTERVAL,
        DEFAULT_AUTH_TIMEOUT,
        DEFAULT_CHROME_DEBUG_PORT,
    )

    return (
        url if url is not None else get_perplexity_base_url(),
        port if port is not None else DEFAULT_CHROME_DEBUG_PORT,
        timeout if timeout is not None else DEFAULT_AUTH_TIMEOUT,
        poll_interval if poll_interval is not None else DEFAULT_AUTH_POLL_INTERVAL,
    )


async def _navigate_and_wait(
    client: ChromeDevToolsClient, url: str, logger: logging.Logger
) -> None:
    """Navigate to the URL and wait for the page to load.

    Args:
        client: Chrome DevTools client instance.
        url: The URL to navigate to.
        logger: Logger instance.
    """
    await client.send_command("Page.enable")
    await client.send_command("Network.enable")

    logger.info("Navigating to %s...", url)
    navigate_result = await client.send_command("Page.navigate", {"url": url})
    logger.debug("Navigation result: %s", navigate_result)

    logger.debug("Waiting for page to load...")
    await _wait_for_page_load(client, timeout=30)


async def _fetch_local_storage(client: ChromeDevToolsClient) -> dict[str, Any]:
    """Fetch localStorage data from the browser.

    Args:
        client: Chrome DevTools client instance.

    Returns:
        Dictionary of localStorage key-value pairs.
    """
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

    if "result" in local_storage_result and "value" in local_storage_result["result"]:
        return local_storage_result["result"]["value"]
    return {}


async def _poll_for_auth_data(
    client: ChromeDevToolsClient,
    # Synchronous urllib polling — asyncio.timeout() not applicable here.
    timeout: int,  # NOSONAR(S7483)
    poll_interval: float,
    logger: logging.Logger,
) -> tuple[str, dict[str, str]]:
    """Poll Chrome for authentication token and cookies.

    Args:
        client: Chrome DevTools client instance.
        timeout: Maximum time to wait in seconds.
        poll_interval: Time between polls in seconds.
        logger: Logger instance.

    Returns:
        Tuple of (token, cookies_dict).

    Raises:
        TimeoutError: If authentication timeout is exceeded.
    """
    start_time = asyncio.get_event_loop().time()

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(
                f"Authentication timeout after {timeout} seconds. "
                "Please ensure you have logged in to Perplexity.ai in Chrome."
            )

        cookies_result = await client.send_command("Network.getAllCookies")
        cookies = cookies_result.get("cookies", [])
        local_storage_data = await _fetch_local_storage(client)

        session_token, cookie_dict = _extract_token(cookies, local_storage_data)

        if session_token:
            logger.info(  # nosemgrep: python-logger-credential-disclosure
                "Successfully extracted authentication token and %s cookies",
                len(cookie_dict),
            )
            return (session_token, cookie_dict)

        logger.debug(  # nosemgrep: python-logger-credential-disclosure
            "No token found yet, waiting %ss... (elapsed: %ss)",
            poll_interval,
            f"{elapsed:.1f}",
        )
        await asyncio.sleep(poll_interval)


async def authenticate_with_browser(
    url: str | None = None,
    port: int | None = None,
    # Synchronous auth flow — asyncio.timeout() not applicable here.
    timeout: int  # NOSONAR(S7483)
    | None = None,
    poll_interval: float | None = None,
) -> tuple[str, dict[str, str]]:
    """Authenticate with Perplexity via Google and extract the session token and cookies.

    Opens Chrome to the Perplexity login page and monitors network traffic
    to capture the authentication token from localStorage and all browser cookies
    (including Cloudflare cookies for bot detection bypass).

    Args:
        url: The Perplexity URL to navigate to. If None, uses configured base URL.
        port: The Chrome remote debugging port (default from config/defaults).
        timeout: Maximum time to wait for authentication in seconds (default from config/defaults).
        poll_interval: Time between polling attempts in seconds (default from config/defaults).

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
    url, port, timeout, poll_interval = _resolve_auth_defaults(url, port, timeout, poll_interval)

    client = ChromeDevToolsClient(port)

    try:
        logger.info("Connecting to Chrome on port %s...", port)
        await client.connect()
        logger.info("Connected to Chrome")

        await _navigate_and_wait(client, url, logger)

        logger.info("Waiting for authentication...")
        return await _poll_for_auth_data(client, timeout, poll_interval, logger)

    finally:
        await client.close()


async def _wait_for_page_load(
    client: ChromeDevToolsClient,
    timeout: int | None = None,  # NOSONAR(S7483)
) -> None:
    """Wait for page to finish loading.

    Args:
        client: Chrome DevTools client instance.
        timeout: Maximum time to wait in seconds (default from config/defaults).

    Raises:
        TimeoutError: If page doesn't load within timeout.
    """
    if timeout is None:
        from perplexity_cli.config.defaults import DEFAULT_PAGE_LOAD_TIMEOUT

        timeout = DEFAULT_PAGE_LOAD_TIMEOUT
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    start_time = asyncio.get_event_loop().time()
    poll_interval = 0.5

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Page load timeout after {timeout} seconds")

        if await _check_page_loaded(client, logger):
            return

        await asyncio.sleep(poll_interval)


async def _check_page_loaded(client: ChromeDevToolsClient, logger: Any) -> bool:
    """Check whether the page has finished loading.

    Args:
        client: Chrome DevTools client instance.
        logger: Logger instance.

    Returns:
        True if the page is loaded, False otherwise.
    """
    try:
        result = await client.send_command("Page.getNavigationHistory")
        if result:
            logger.debug("Page loaded successfully")
            return True
    except AuthenticationError as e:
        logger.debug("Page not ready yet: %s", e)
    return False


def _extract_token(
    cookies: list[dict[str, Any]], local_storage: dict[str, Any]
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
    cookie_dict = {c["name"]: c["value"] for c in cookies}
    token = _extract_token_from_local_storage(local_storage)
    if not token:
        token = _extract_token_from_cookies(cookie_dict)
    return (token, cookie_dict)


def _extract_token_from_local_storage(local_storage: dict[str, Any]) -> str | None:
    """Attempt to extract an authentication token from localStorage.

    Args:
        local_storage: Dictionary of localStorage key-value pairs.

    Returns:
        The token string, or None if not found.
    """
    if "pplx-next-auth-session" not in local_storage:
        return None
    try:
        session_data = json.loads(local_storage["pplx-next-auth-session"])
        return json.dumps(session_data)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_token_from_cookies(cookie_dict: dict[str, str]) -> str | None:
    """Attempt to extract an authentication token from cookies as a fallback.

    Args:
        cookie_dict: Dictionary of browser cookies.

    Returns:
        The token string, or None if not found.
    """
    for cookie_name in ["__Secure-next-auth.session-token", "next-auth.session-token"]:
        if cookie_name in cookie_dict:
            return cookie_dict[cookie_name]
    return None


def authenticate_sync(
    url: str | None = None,
    port: int | None = None,
    timeout: int | None = None,
    poll_interval: float | None = None,
) -> tuple[str, dict[str, str]]:
    """Synchronous wrapper for authenticate_with_browser.

    Args:
        url: The Perplexity URL to navigate to. If None, uses configured base URL.
        port: The Chrome remote debugging port (default from config/defaults).
        timeout: Maximum time to wait for authentication in seconds (default from config/defaults).
        poll_interval: Time between polling attempts in seconds (default from config/defaults).

    Returns:
        Tuple of (token, cookies_dict) where:
            - token: The extracted authentication token
            - cookies_dict: Dictionary of all browser cookies {name: value}

    Raises:
        RuntimeError: If Chrome is not available or authentication fails.
        TimeoutError: If authentication timeout is exceeded.
    """
    return run_async(authenticate_with_browser(url, port, timeout, poll_interval))
