"""HTTP client for Perplexity API with SSE streaming support."""

import json
from collections.abc import Iterator

import httpx

from perplexity_cli.utils.logging import get_logger
from perplexity_cli.utils.retry import is_retryable_error
from perplexity_cli.utils.version import get_version


class SSEClient:
    """HTTP client with Server-Sent Events (SSE) streaming support."""

    def __init__(self, token: str, cookies: dict[str, str] | None = None, timeout: int = 60, max_retries: int = 3) -> None:
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

        while attempt < self.max_retries:
            try:
                self.logger.debug(
                    f"Streaming POST to {url} (attempt {attempt + 1}/{self.max_retries})"
                )

                with httpx.Client(timeout=self.timeout) as client:
                    with client.stream("POST", url, headers=headers, json=json_data) as response:
                        # Check for HTTP errors
                        response.raise_for_status()

                        # Parse SSE stream - once streaming starts, we can't retry
                        yield from self._parse_sse_stream(response)
                        return  # Success, exit retry loop

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                # Don't retry auth errors (401, 403)
                if status in (401, 403):
                    self.logger.error(f"HTTP {status} error (not retryable): {e}")
                    if status == 401:
                        raise httpx.HTTPStatusError(
                            "Authentication failed. Token may be invalid or expired.",
                            request=e.request,
                            response=e.response,
                        ) from e
                    elif status == 403:
                        raise httpx.HTTPStatusError(
                            "Access forbidden. Check API permissions.",
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
