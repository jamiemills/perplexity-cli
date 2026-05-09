"""HTTP client for Perplexity API with SSE streaming support.

Uses curl_cffi to impersonate Chrome's TLS fingerprint, which is required
to pass Cloudflare's bot protection on Perplexity's API endpoints. The
cf_clearance cookie is bound to the TLS fingerprint of the client that
solved the JavaScript challenge, so Python's default TLS stack (used by
httpx/urllib3) is rejected even with valid cookies.

Exceptions are raised as custom PerplexityHTTPStatusError and
PerplexityRequestError types defined in utils/exceptions.py.
"""

import json
import logging
import time
from collections.abc import Iterator

try:
    from curl_cffi.requests import Session
    from curl_cffi.requests.exceptions import RequestException

    _CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    Session = None  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    RequestException = Exception  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    _CURL_CFFI_AVAILABLE = False

from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import raise_http_status_error
from perplexity_cli.utils.http_headers import build_perplexity_headers
from perplexity_cli.utils.logging import (
    get_logger,
    redact_mapping_keys,
    redact_response_text,
    redact_url,
)
from perplexity_cli.utils.retry import get_backoff_delay, get_retry_after_delay, is_retryable_error


class SSEClient:
    """HTTP client with Server-Sent Events (SSE) streaming support.

    Uses curl_cffi with Chrome TLS fingerprint impersonation to bypass
    Cloudflare's bot protection.
    """

    def __init__(
        self,
        token: str | None,
        cookies: dict[str, str] | None = None,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> None:
        """Initialise SSE client.

        Args:
            token: Optional authentication JWT token.
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
        return build_perplexity_headers(
            self.token,
            self.cookies,
            accept="text/event-stream",
        )

    def _get_client(self) -> Session:
        """Get or create the persistent curl_cffi session.

        Returns:
            The shared Session instance with Chrome TLS impersonation.

        Raises:
            RuntimeError: If curl_cffi is not installed.
        """
        if self._client is None:
            from perplexity_cli.utils.session_factory import create_sync_session

            self._client = create_sync_session(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the persistent session if open."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _resolve_effective_timeout(self, json_data: dict) -> tuple[bool, int]:
        """Determine the effective timeout based on query parameters.

        Deep research requests use a longer timeout (360s) to accommodate
        multi-step processing.

        Args:
            json_data: JSON request body.

        Returns:
            Tuple of (is_deep_research, effective_timeout_seconds).
        """
        is_deep_research = (
            json_data.get("params", {}).get("search_implementation_mode") == "multi_step"
        )
        effective_timeout = 360 if is_deep_research else self.timeout
        return is_deep_research, effective_timeout

    def _log_request_context(
        self,
        url: str,
        headers: dict[str, str],
        is_deep_research: bool,
        effective_timeout: int,
    ) -> None:
        """Log debug context for an outbound request.

        Only emits output when the logger is at DEBUG level.

        Args:
            url: The API endpoint URL.
            headers: Request headers.
            is_deep_research: Whether deep research mode is active.
            effective_timeout: The timeout that will be used.
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        self.logger.debug(f"API Request to: {redact_url(url)}")
        self.logger.debug(f"Request headers: Content-Type={headers.get('Content-Type')}")
        if is_deep_research:
            self.logger.debug(f"Deep research mode detected, timeout set to {effective_timeout}s")

        has_auth = bool(self.token)
        cookies = self.cookies
        self.logger.debug(f"Authentication: Bearer token present={has_auth}")
        if cookies:
            cookie_names = list(cookies.keys())
            cf_cookies = [c for c in cookie_names if c.startswith("cf") or c.startswith("__cf")]
            self.logger.debug(
                f"Cookies: {len(cookies)} total, {len(cf_cookies)} Cloudflare-related"
            )
            self.logger.debug(f"Cloudflare cookies present: {redact_mapping_keys(cookies)}")
        else:
            self.logger.debug("Cookies: None (no Cloudflare bypass)")

    def _log_http_error_context(self, error: PerplexityHTTPStatusError) -> None:
        """Log debug context for an HTTP error response.

        Captures Cloudflare headers and a redacted response body preview.
        Only emits output when the logger is at DEBUG level.

        Args:
            error: The HTTP status error to log.
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        status = error.response.status_code
        self.logger.debug(f"HTTP Error {status}: {error}")
        cf_ray = error.response.headers.get("cf-ray")
        if cf_ray:
            self.logger.debug(f"Cloudflare Ray ID: {cf_ray}")
        cf_cache = error.response.headers.get("cf-cache-status")
        if cf_cache:
            self.logger.debug(f"Cloudflare Cache Status: {cf_cache}")

        try:
            response_text = error.response.text[:500]
            self.logger.debug(f"Response body preview: {redact_response_text(response_text)}")
        except (AttributeError, TypeError):
            pass

    def _handle_http_error(self, error: PerplexityHTTPStatusError, attempt: int) -> float:
        """Classify an HTTP error and decide whether to retry.

        Returns the wait time in seconds when the error is retryable and
        attempts remain.  Raises immediately for non-retryable errors or
        when retries are exhausted.

        Args:
            error: The HTTP status error.
            attempt: Current attempt number (0-indexed).

        Returns:
            Wait time in seconds if the request should be retried.

        Raises:
            PerplexityHTTPStatusError: When the error is not retryable or
                retries are exhausted.
        """
        self._log_http_error_context(error)
        status = error.response.status_code

        # 401: never retry — token is invalid
        if status == 401:
            self.logger.error(f"HTTP {status} error (not retryable): {error}")
            raise PerplexityHTTPStatusError(
                "Authentication failed. Token may be invalid or expired.",
                request=error.request,
                response=error.response,
            ) from error

        # 403: retry (Cloudflare challenge / transient block)
        if status == 403:
            if attempt < self.max_retries - 1:
                next_attempt = attempt + 1
                wait_time = get_backoff_delay(next_attempt)
                self.logger.warning(
                    f"HTTP 403 error (may be Cloudflare blocking), retrying in {wait_time}s "
                    f"(attempt {next_attempt + 1}/{self.max_retries})"
                )
                return wait_time
            self.logger.error(
                f"HTTP {status} error (not retryable after {self.max_retries} attempts): {error}"
            )
            raise PerplexityHTTPStatusError(
                "Access forbidden. Check API permissions or try again later.",
                request=error.request,
                response=error.response,
            ) from error

        # 429 / 5xx: retry with Retry-After support
        if is_retryable_error(error) and attempt < self.max_retries - 1:
            next_attempt = attempt + 1
            wait_time = get_retry_after_delay(error)
            if wait_time is None:
                wait_time = get_backoff_delay(next_attempt)
            self.logger.warning(
                f"HTTP {status} error, retrying in {wait_time}s "
                f"(attempt {next_attempt + 1}/{self.max_retries})"
            )
            return wait_time

        # Exhausted retries or non-retryable status
        if status == 429:
            raise PerplexityHTTPStatusError(
                "Rate limit exceeded. Please wait and try again.",
                request=error.request,
                response=error.response,
            ) from error
        raise error

    def stream_post(self, url: str, json_data: dict) -> Iterator[dict]:
        """POST request with SSE streaming response.

        Args:
            url: The API endpoint URL.
            json_data: JSON request body.

        Yields:
            Parsed JSON data from each SSE message.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors (401, 403, 500, etc.).
            PerplexityRequestError: For network/connection errors.
            ValueError: For malformed SSE messages.
        """
        headers = self.get_headers()
        is_deep_research, effective_timeout = self._resolve_effective_timeout(json_data)
        self._log_request_context(url, headers, is_deep_research, effective_timeout)

        attempt = 0
        while attempt < self.max_retries:
            try:
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        f"Streaming POST to {redact_url(url)} (attempt {attempt + 1}/{self.max_retries})"
                    )

                client = self._get_client()
                with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=json_data,
                    cookies=to_curl_cffi_cookies(self.cookies),
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

                    if not response.ok:
                        raise_http_status_error(response)

                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("Starting SSE stream parsing")

                    yield from self._parse_sse_stream(response)

                    if self.logger.isEnabledFor(logging.DEBUG):
                        self.logger.debug("SSE stream completed successfully")
                    return  # Success, exit retry loop

            except PerplexityHTTPStatusError as e:
                wait_time = self._handle_http_error(e, attempt)
                attempt += 1
                time.sleep(wait_time)
                continue

            except PerplexityRequestError as e:
                if is_retryable_error(e) and attempt < self.max_retries - 1:
                    attempt += 1
                    self.logger.warning(
                        f"Network error, retrying (attempt {attempt + 1}/{self.max_retries}): {e}"
                    )
                    continue
                self.logger.error(f"Network error after {attempt + 1} attempts: {e}")
                raise

            except RequestException as e:
                self.logger.error(f"Network error after {attempt + 1} attempts: {e}")
                raise PerplexityRequestError(str(e)) from e

            except (ValueError, TypeError, AttributeError) as e:
                self.logger.error(f"Unexpected error during streaming: {e}", exc_info=True)
                raise

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
            UpstreamSchemaError: If SSE format is invalid or JSON cannot be parsed.
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
                        raise UpstreamSchemaError(
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
                raise UpstreamSchemaError(
                    f"Failed to parse SSE data as JSON: {data_str[:100]}"
                ) from e
