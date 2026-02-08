"""HTTP client for Perplexity API with SSE streaming support."""

import json
import logging
import time
from collections.abc import Iterator

import httpx

from perplexity_cli.utils.logging import get_logger
from perplexity_cli.utils.retry import is_retryable_error
from perplexity_cli.utils.version import get_version


class SSEClient:
    """HTTP client with Server-Sent Events (SSE) streaming support."""

    def __init__(
        self,
        token: str,
        cookies: dict[str, str] | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        """Initialise SSE client.

        Args:
            token: Authentication JWT token.
            cookies: Optional browser cookies for Cloudflare bypass.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for initial connection.
        """
        self.token = token
        self.cookies = cookies
        self.timeout = timeout
        self.max_retries = max_retries
        self.logger = get_logger()
        self._client: httpx.Client | None = None

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests.

        Returns:
            Dictionary of HTTP headers including authentication and cookies.
        """
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": f"perplexity-cli/{get_version()}",
            "Origin": "https://www.perplexity.ai",
            "Referer": "https://www.perplexity.ai/",
        }

        # Add cookies if available (for Cloudflare bypass)
        if self.cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
            headers["Cookie"] = cookie_str

        return headers

    def _get_client(self) -> httpx.Client:
        """Get or create the persistent httpx client.

        Returns:
            The shared httpx.Client instance.
        """
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the persistent httpx client if open."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def stream_post(self, url: str, json_data: dict) -> Iterator[dict]:
        """POST request with SSE streaming response.

        Args:
            url: The API endpoint URL.
            json_data: JSON request body.

        Yields:
            Parsed JSON data from each SSE message.

        Raises:
            httpx.HTTPStatusError: For HTTP errors (401, 403, 500, etc.).
            httpx.RequestError: For network/connection errors.
            ValueError: For malformed SSE messages.
        """
        headers = self.get_headers()
        attempt = 0

        if self.logger.isEnabledFor(logging.DEBUG):
            # Debug: Log request details at startup
            self.logger.debug(f"API Request to: {url}")
            self.logger.debug(
                f"Request headers: Content-Type={headers.get('Content-Type')}, User-Agent={headers.get('User-Agent')}"
            )

            # Debug: Log authentication and cookie status
            has_auth = bool(self.token)
            has_cookies = bool(self.cookies)
            self.logger.debug(f"Authentication: Bearer token present={has_auth}")
            if has_cookies:
                cookie_names = list(self.cookies.keys())
                cf_cookies = [c for c in cookie_names if c.startswith("cf") or c.startswith("__cf")]
                self.logger.debug(
                    f"Cookies: {len(self.cookies)} total, {len(cf_cookies)} Cloudflare-related"
                )
                self.logger.debug(f"Cloudflare cookies present: {cf_cookies}")
            else:
                self.logger.debug("Cookies: None (no Cloudflare bypass)")

        while attempt < self.max_retries:
            try:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        f"Streaming POST to {url} (attempt {attempt + 1}/{self.max_retries})"
                    )

                client = self._get_client()
                with client.stream("POST", url, headers=headers, json=json_data) as response:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        # Debug: Log response status and Cloudflare headers
                        self.logger.debug(f"HTTP {response.status_code} {response.reason_phrase}")
                        cf_ray = response.headers.get("cf-ray")
                        if cf_ray:
                            self.logger.debug(f"Cloudflare Ray ID: {cf_ray}")
                        cf_cache = response.headers.get("cf-cache-status")
                        if cf_cache:
                            self.logger.debug(f"Cloudflare Cache Status: {cf_cache}")
                        server = response.headers.get("server")
                        if server:
                            self.logger.debug(f"Server: {server}")

                    # Check for HTTP errors
                    response.raise_for_status()

                    if self.logger.isEnabledFor(logging.DEBUG):
                        # Parse SSE stream - once streaming starts, we can't retry
                        self.logger.debug("Starting SSE stream parsing")

                    yield from self._parse_sse_stream(response)

                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("SSE stream completed successfully")
                    return  # Success, exit retry loop

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if self.logger.isEnabledFor(logging.DEBUG):
                    # Debug: Log response headers and body preview for all errors
                    self.logger.debug(f"HTTP Error {status}: {e}")
                    cf_ray = e.response.headers.get("cf-ray")
                    if cf_ray:
                        self.logger.debug(f"Cloudflare Ray ID: {cf_ray}")
                    cf_cache = e.response.headers.get("cf-cache-status")
                    if cf_cache:
                        self.logger.debug(f"Cloudflare Cache Status: {cf_cache}")

                    # Log response body preview for debugging
                    try:
                        response_text = e.response.text[:500]
                        self.logger.debug(f"Response body preview: {response_text}")
                    except Exception:
                        pass

                # Don't retry 401 (invalid token), but 403 might be temporary Cloudflare blocking
                if status == 401:
                    self.logger.error(f"HTTP {status} error (not retryable): {e}")
                    raise httpx.HTTPStatusError(
                        "Authentication failed. Token may be invalid or expired.",
                        request=e.request,
                        response=e.response,
                    ) from e

                # Retry 403 errors (might be Cloudflare challenge/rate limit)
                if status == 403:
                    if attempt < self.max_retries - 1:
                        attempt += 1
                        # Use exponential backoff: 2s, 4s, 8s
                        wait_time = 2**attempt
                        self.logger.warning(
                            f"HTTP 403 error (may be Cloudflare blocking), retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        self.logger.error(
                            f"HTTP {status} error (not retryable after {self.max_retries} attempts): {e}"
                        )
                        raise httpx.HTTPStatusError(
                            "Access forbidden. Check API permissions or try again later.",
                            request=e.request,
                            response=e.response,
                        ) from e

                # Retry 429 and 5xx errors
                if is_retryable_error(e) and attempt < self.max_retries - 1:
                    attempt += 1
                    self.logger.warning(
                        f"HTTP {status} error, retrying (attempt {attempt + 1}/{self.max_retries})"
                    )
                    continue

                # Re-raise if not retryable or out of retries
                if status == 429:
                    raise httpx.HTTPStatusError(
                        "Rate limit exceeded. Please wait and try again.",
                        request=e.request,
                        response=e.response,
                    ) from e
                raise

            except httpx.RequestError as e:
                # Retry network errors
                if is_retryable_error(e) and attempt < self.max_retries - 1:
                    attempt += 1
                    self.logger.warning(
                        f"Network error, retrying (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    continue
                # Re-raise if out of retries
                self.logger.error(f"Network error after {attempt + 1} attempts: {e}")
                raise

            except Exception as e:
                # Don't retry other exceptions
                self.logger.error(f"Unexpected error during streaming: {e}", exc_info=True)
                raise

    def _parse_sse_stream(self, response: httpx.Response) -> Iterator[dict]:
        """Parse Server-Sent Events stream.

        SSE format:
            event: message
            data: {json}

            event: message
            data: {json}

        Args:
            response: The streaming HTTP response.

        Yields:
            Parsed JSON data from each SSE message.

        Raises:
            ValueError: If SSE format is invalid or JSON cannot be parsed.
        """
        event_type = None
        data_lines = []

        for line in response.iter_lines():
            # Empty line indicates end of message
            if not line:
                if event_type and data_lines:
                    # Join multi-line data and parse JSON
                    data_str = "\n".join(data_lines)
                    try:
                        yield json.loads(data_str)
                    except json.JSONDecodeError as e:
                        raise ValueError(
                            f"Failed to parse SSE data as JSON: {data_str[:100]}"
                        ) from e

                # Reset for next message
                event_type = None
                data_lines = []
                continue

            # Parse event type
            if line.startswith("event:"):
                event_type = line[6:].strip()

            # Parse data
            elif line.startswith("data:"):
                data_content = line[5:].strip()
                data_lines.append(data_content)

        # Handle final message if stream ends without empty line
        if event_type and data_lines:
            data_str = "\n".join(data_lines)
            try:
                yield json.loads(data_str)
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse SSE data as JSON: {data_str[:100]}") from e
