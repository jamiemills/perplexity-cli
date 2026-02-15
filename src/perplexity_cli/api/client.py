"""HTTP client for Perplexity API with SSE streaming support.

Uses curl_cffi to impersonate Chrome's TLS fingerprint, which is required
to pass Cloudflare's bot protection on Perplexity's API endpoints. The
cf_clearance cookie is bound to the TLS fingerprint of the client that
solved the JavaScript challenge, so Python's default TLS stack (used by
httpx/urllib3) is rejected even with valid cookies.

Exceptions are converted to httpx types so that downstream error handling
(cli.py, http_errors.py, retry.py) does not need to change.
"""

import json
import logging
import time
from collections.abc import Iterator

import httpx
from curl_cffi.requests import Session
from curl_cffi.requests.exceptions import RequestException

from perplexity_cli.utils.logging import get_logger
from perplexity_cli.utils.retry import is_retryable_error


class SSEClient:
    """HTTP client with Server-Sent Events (SSE) streaming support.

    Uses curl_cffi with Chrome TLS fingerprint impersonation to bypass
    Cloudflare's bot protection.
    """

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
        self._client: Session | None = None

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests.

        curl_cffi sets User-Agent automatically based on the impersonated
        browser, so it is not included here. Cookies are passed separately
        via the ``cookies`` parameter on requests rather than as a header.

        Returns:
            Dictionary of HTTP headers including authentication.
        """
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Origin": "https://www.perplexity.ai",
            "Referer": "https://www.perplexity.ai/",
        }

        # Add CSRF token from cookies if available
        if self.cookies and "csrftoken" in self.cookies:
            headers["X-CSRFToken"] = self.cookies["csrftoken"]

        return headers

    def _get_client(self) -> Session:
        """Get or create the persistent curl_cffi session.

        Returns:
            The shared Session instance with Chrome TLS impersonation.
        """
        if self._client is None:
            self._client = Session(impersonate="chrome", timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the persistent session if open."""
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

        # Check if deep research is requested and adjust timeout accordingly
        is_deep_research = (
            json_data.get("params", {}).get("search_implementation_mode") == "multi_step"
        )
        effective_timeout = 360 if is_deep_research else self.timeout

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"API Request to: {url}")
            self.logger.debug(f"Request headers: Content-Type={headers.get('Content-Type')}")
            if is_deep_research:
                self.logger.debug(
                    f"Deep research mode detected, timeout set to {effective_timeout}s"
                )

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
                with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=json_data,
                    cookies=self.cookies or {},
                    timeout=effective_timeout,
                ) as response:
                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug(f"HTTP {response.status_code} {response.reason}")
                        cf_ray = response.headers.get("cf-ray")
                        if cf_ray:
                            self.logger.debug(f"Cloudflare Ray ID: {cf_ray}")
                        cf_cache = response.headers.get("cf-cache-status")
                        if cf_cache:
                            self.logger.debug(f"Cloudflare Cache Status: {cf_cache}")
                        server = response.headers.get("server")
                        if server:
                            self.logger.debug(f"Server: {server}")

                    # Check for HTTP errors - convert to httpx exception types
                    if not response.ok:
                        self._raise_http_status_error(response)

                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("Starting SSE stream parsing")

                    yield from self._parse_sse_stream(response)

                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("SSE stream completed successfully")
                    return  # Success, exit retry loop

            except httpx.HTTPStatusError as e:
                status = e.response.status_code

                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(f"HTTP Error {status}: {e}")
                    cf_ray = e.response.headers.get("cf-ray")
                    if cf_ray:
                        self.logger.debug(f"Cloudflare Ray ID: {cf_ray}")
                    cf_cache = e.response.headers.get("cf-cache-status")
                    if cf_cache:
                        self.logger.debug(f"Cloudflare Cache Status: {cf_cache}")

                    try:
                        response_text = e.response.text[:500]
                        self.logger.debug(f"Response body preview: {response_text}")
                    except Exception:
                        pass

                # Don't retry 401 (invalid token)
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
                self.logger.error(f"Network error after {attempt + 1} attempts: {e}")
                raise

            except RequestException as e:
                # Convert curl_cffi network errors to httpx.RequestError
                self.logger.error(f"Network error after {attempt + 1} attempts: {e}")
                raise httpx.RequestError(str(e)) from e

            except Exception as e:
                self.logger.error(f"Unexpected error during streaming: {e}", exc_info=True)
                raise

    @staticmethod
    def _raise_http_status_error(response) -> None:
        """Convert a curl_cffi error response into an httpx.HTTPStatusError.

        Constructs a minimal httpx.Request and httpx.Response so that
        downstream error handlers can access ``.status_code``, ``.headers``,
        and ``.text`` as they would with a native httpx error.

        Args:
            response: The curl_cffi Response object with a non-2xx status.

        Raises:
            httpx.HTTPStatusError: Always raised with the converted response.
        """
        # Build an httpx-compatible Request object
        httpx_request = httpx.Request(
            method="POST",
            url=response.url,
        )

        # Read the response body so it's available via .text on the httpx Response
        try:
            body = response.content
        except Exception:
            body = b""

        # Build an httpx-compatible Response object
        httpx_response = httpx.Response(
            status_code=response.status_code,
            headers=dict(response.headers),
            content=body,
            request=httpx_request,
        )

        raise httpx.HTTPStatusError(
            f"HTTP Error {response.status_code}: {response.reason}",
            request=httpx_request,
            response=httpx_response,
        )

    def _parse_sse_stream(self, response) -> Iterator[dict]:
        """Parse Server-Sent Events stream.

        SSE format:
            event: message
            data: {json}

            event: message
            data: {json}

        curl_cffi's ``iter_lines()`` yields bytes, so each line is decoded
        to a string before parsing.

        Args:
            response: The streaming HTTP response (curl_cffi Response).

        Yields:
            Parsed JSON data from each SSE message.

        Raises:
            ValueError: If SSE format is invalid or JSON cannot be parsed.
        """
        event_type = None
        data_lines = []

        for raw_line in response.iter_lines():
            # Decode bytes to string
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line

            # Empty line indicates end of message
            if not line:
                if event_type and data_lines:
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
