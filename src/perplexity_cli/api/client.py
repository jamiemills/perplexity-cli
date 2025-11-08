"""HTTP client for Perplexity API with SSE streaming support."""

import json
from collections.abc import Iterator

import httpx


class SSEClient:
    """HTTP client with Server-Sent Events (SSE) streaming support."""

    def __init__(self, token: str, timeout: int = 60) -> None:
        """Initialise SSE client.

        Args:
            token: Authentication JWT token.
            timeout: Request timeout in seconds.
        """
        self.token = token
        self.timeout = timeout

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests.

        Returns:
            Dictionary of HTTP headers including authentication.
        """
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "perplexity-cli/0.1.0",
        }

    def stream_post(
        self, url: str, json_data: dict
    ) -> Iterator[dict]:
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

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST", url, headers=headers, json=json_data
                ) as response:
                    # Check for HTTP errors
                    response.raise_for_status()

                    # Parse SSE stream
                    yield from self._parse_sse_stream(response)

        except httpx.HTTPStatusError as e:
            # Re-raise with more context
            status = e.response.status_code
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
            elif status == 429:
                raise httpx.HTTPStatusError(
                    "Rate limit exceeded. Please wait and try again.",
                    request=e.request,
                    response=e.response,
                ) from e
            else:
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
                raise ValueError(
                    f"Failed to parse SSE data as JSON: {data_str[:100]}"
                ) from e
