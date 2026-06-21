"""HTTP client for Perplexity API with SSE streaming support.

Uses curl_cffi to impersonate Chrome's TLS fingerprint, which is required
to pass Cloudflare's bot protection on Perplexity's API endpoints. The
cf_clearance cookie is bound to the TLS fingerprint of the client that
solved the JavaScript challenge, so Python's default TLS stack (used by
httpx/urllib3) is rejected even with valid cookies.

Exceptions are raised as custom PerplexityHTTPStatusError and
PerplexityRequestError types defined in utils/exceptions.py.
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
from collections.abc import Iterator
from typing import Final, TypeGuard

from perplexity_cli.api.models import HttpRequestContext
from perplexity_cli.auth.models import AuthContext
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
from perplexity_cli.utils.retry import (
    get_backoff_delay,
    get_retry_after_delay,
    is_retryable_error,
    sleep_with_backoff,
)

_CurlRequestException: type[Exception] | None
try:
    from curl_cffi.requests.exceptions import RequestException as _ImportedCurlRequestException
except ImportError:  # pragma: no cover
    _CurlRequestException = None
    _curl_cffi_available = False
else:
    _CurlRequestException = _ImportedCurlRequestException
    _curl_cffi_available = True

HTTP_STATUS_UNAUTHORISED: Final[int] = 401
HTTP_STATUS_FORBIDDEN: Final[int] = 403
HTTP_STATUS_TOO_MANY_REQUESTS: Final[int] = 429
DEEP_RESEARCH_TIMEOUT_MODE: Final[str] = "multi_step"
HEADER_PAIR_SIZE: Final[int] = 2
DEEP_RESEARCH_MODE_KEYS: Final[tuple[str, ...]] = (
    "searchModeOverride",
    "search_mode",
    "workflow_key",
)
DEEP_RESEARCH_MODE_VALUES: Final[frozenset[str]] = frozenset(
    {"research", "deep_research", "RESEARCH"}
)

type JsonObject = dict[str, object]


def _require_str(value: object, context: str) -> str:
    """Return *value* as a string or raise for an invalid transport shape."""
    if isinstance(value, str):
        return value
    raise RuntimeError(f"Expected string transport attribute for {context}")


def _require_int(value: object, context: str) -> int:
    """Return *value* as an integer or raise for an invalid transport shape."""
    if isinstance(value, int):
        return value
    raise RuntimeError(f"Expected integer transport attribute for {context}")


def _require_bool(value: object, context: str) -> bool:
    """Return *value* as a boolean or raise for an invalid transport shape."""
    if isinstance(value, bool):
        return value
    raise RuntimeError(f"Expected boolean transport attribute for {context}")


def _require_bytes_or_str(value: object, context: str) -> bytes | str:
    """Return *value* as bytes or string or raise for an invalid shape."""
    if isinstance(value, bytes | str):
        return value
    raise RuntimeError(f"Expected bytes-or-string transport attribute for {context}")


def _require_json_object_or_none(value: object, context: str) -> JsonObject | None:
    """Return *value* as a JSON object or ``None``."""
    if value is None:
        return None
    if _is_json_object(value):
        return value
    raise RuntimeError(f"Expected JSON object transport attribute for {context}")


def _is_deep_research_value(value: object) -> bool:
    """Return whether a query parameter selects deep research mode."""
    return isinstance(value, str) and value in DEEP_RESEARCH_MODE_VALUES


def _is_deep_research_request(params: JsonObject) -> bool:
    """Return whether request parameters opt into deep research mode."""
    if params.get("search_implementation_mode") == DEEP_RESEARCH_TIMEOUT_MODE:
        return True
    return any(_is_deep_research_value(params.get(key)) for key in DEEP_RESEARCH_MODE_KEYS)


def _iter_object_values(value: object, context: str) -> Iterator[object]:
    """Yield objects from an untyped iterable transport value."""
    iter_attr = getattr(value, "__iter__", None)
    if not callable(iter_attr):
        raise RuntimeError(f"Expected iterable transport value for {context}")

    iterator = iter_attr()
    next_attr = getattr(iterator, "__next__", None)
    if not callable(next_attr):
        raise RuntimeError(f"Expected iterator transport value for {context}")

    while True:
        try:
            yield next_attr()
        except StopIteration:
            return


def _coerce_header_pair(item: object, context: str) -> tuple[str, str]:
    """Coerce one header item into a string pair."""
    len_attr = getattr(item, "__len__", None)
    getitem_attr = getattr(item, "__getitem__", None)
    if not callable(len_attr) or not callable(getitem_attr):
        raise RuntimeError(f"Expected header pair items for {context}")
    size = len_attr()
    if not isinstance(size, int) or size != HEADER_PAIR_SIZE:
        raise RuntimeError(f"Expected header pair items for {context}")
    return str(getitem_attr(0)), str(getitem_attr(1))


def _coerce_header_mapping(value: object, context: str) -> dict[str, str]:
    """Coerce header-like items into a standard string dictionary."""
    items_attr = getattr(value, "items", None)
    if not callable(items_attr):
        raise RuntimeError(f"Expected mapping-like transport attribute for {context}")

    items_result_object = items_attr()

    headers: dict[str, str] = {}
    for raw_item in _iter_object_values(items_result_object, context):
        key, header_value = _coerce_header_pair(raw_item, context)
        headers[key] = header_value
    return headers


class _ResponseAdapter:
    """Typed wrapper around an untyped curl_cffi response object."""

    def __init__(self, response: object) -> None:
        self._response = response

    @property
    def status_code(self) -> int:
        return _require_int(getattr(self._response, "status_code", None), "response.status_code")

    @property
    def headers(self) -> dict[str, str]:
        return _coerce_header_mapping(getattr(self._response, "headers", None), "response.headers")

    @property
    def text(self) -> str:
        return _require_str(getattr(self._response, "text", None), "response.text")

    @property
    def ok(self) -> bool:
        return _require_bool(getattr(self._response, "ok", None), "response.ok")

    @property
    def reason(self) -> str:
        return _require_str(getattr(self._response, "reason", None), "response.reason")

    @property
    def url(self) -> object:
        return getattr(self._response, "url", None)

    @property
    def content(self) -> bytes | str:
        return _require_bytes_or_str(getattr(self._response, "content", None), "response.content")

    def iter_lines(self) -> Iterator[bytes | str]:
        iter_lines_attr = getattr(self._response, "iter_lines", None)
        if not callable(iter_lines_attr):
            raise RuntimeError("Expected callable response.iter_lines transport method")

        lines_result_object = iter_lines_attr()
        for raw_line in _iter_object_values(lines_result_object, "response.iter_lines"):
            if not isinstance(raw_line, bytes | str):
                raise RuntimeError("Expected bytes or string lines from response.iter_lines")
            yield raw_line


class _StreamContextAdapter:
    """Typed wrapper around the ``Session.stream`` context manager."""

    def __init__(self, context: object) -> None:
        self._context = context

    def __enter__(self) -> _ResponseAdapter:
        enter_attr = getattr(self._context, "__enter__", None)
        if not callable(enter_attr):
            raise RuntimeError("Expected __enter__ on stream context manager")
        return _ResponseAdapter(enter_attr())

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool | None:
        exit_attr = getattr(self._context, "__exit__", None)
        if not callable(exit_attr):
            raise RuntimeError("Expected __exit__ on stream context manager")
        result = exit_attr(exc_type, exc_value, traceback)
        if result is None or isinstance(result, bool):
            return result
        raise RuntimeError("Expected bool-or-None return from stream context manager")


def _create_transport_session(timeout: int) -> object:
    """Create the underlying curl_cffi session as an untyped transport object."""
    session_factory_module = importlib.import_module("perplexity_cli.utils.session_factory")
    create_sync_session = getattr(session_factory_module, "create_sync_session", None)
    if not callable(create_sync_session):
        raise RuntimeError("Expected callable create_sync_session transport factory")

    session = create_sync_session(timeout=timeout)
    return session


def _close_transport_session(session: object) -> None:
    """Close the underlying transport session."""
    close_attr = getattr(session, "close", None)
    if not callable(close_attr):
        raise RuntimeError("Expected callable session.close transport method")
    close_attr()


def _open_stream_context(
    session: object,
    ctx: HttpRequestContext,
    cookies: object,
) -> _StreamContextAdapter:
    """Open a typed stream context from the untyped transport session."""
    stream_attr = getattr(session, "stream", None)
    if not callable(stream_attr):
        raise RuntimeError("Expected callable session.stream transport method")

    return _StreamContextAdapter(
        stream_attr(
            "POST",
            ctx.url,
            headers=ctx.headers,
            json=_require_json_object_or_none(ctx.json_data, "stream.json"),
            cookies=cookies,
            timeout=ctx.effective_timeout,
        )
    )


def _is_json_object(value: object) -> TypeGuard[JsonObject]:
    """Return whether *value* is a JSON-like object with string keys."""
    return isinstance(value, dict)


def _is_request_exception(error: Exception) -> bool:
    """Return whether *error* is the transport-layer request exception type."""
    if not _curl_cffi_available or _CurlRequestException is None:
        return False
    return isinstance(error, _CurlRequestException)


# ---------------------------------------------------------------------------
# Extracted: SSE protocol parser (stateless)
# ---------------------------------------------------------------------------


class SSEParser:
    """Stateless parser for the Server-Sent Events wire format.

    All methods are static; the class serves as a namespace and keeps the
    parsing logic isolated from HTTP transport concerns.
    """

    @staticmethod
    def parse(response: _ResponseAdapter, logger: logging.Logger) -> Iterator[JsonObject]:
        """Parse an SSE stream from *response* into JSON events.

        Args:
            response: A streaming HTTP response (curl_cffi Response).
            logger: Logger for debug output.

        Yields:
            Parsed JSON dictionary per SSE event.

        Raises:
            UpstreamSchemaError: If SSE format is invalid or JSON fails.
        """
        event_type: str | None = None
        data_lines: list[str] = []

        for raw_line in response.iter_lines():
            line = SSEParser._decode_line(raw_line)
            event_type, data_lines, event = SSEParser._accumulate_line(line, event_type, data_lines)
            if event is not None:
                yield event

        # Handle final message if stream ends without empty line.
        if event_type and data_lines:
            yield SSEParser._yield_event(data_lines)

    @staticmethod
    def _decode_line(raw_line: bytes | str) -> str:
        """Decode a raw SSE line from bytes to string if necessary."""
        return raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line

    @staticmethod
    def _accumulate_line(
        line: str,
        event_type: str | None,
        data_lines: list[str],
    ) -> tuple[str | None, list[str], JsonObject | None]:
        """Process a single decoded SSE line, potentially yielding an event.

        Args:
            line: The decoded SSE line.
            event_type: Current event type.
            data_lines: Current accumulated data lines.

        Returns:
            Tuple of (updated event_type, updated data_lines, event or None).
        """
        if not line:
            event = SSEParser._yield_event(data_lines) if event_type and data_lines else None
            return None, [], event

        updated_type, updated_lines = SSEParser._parse_line(line, event_type, data_lines)
        return updated_type, updated_lines, None

    @staticmethod
    def _yield_event(data_lines: list[str]) -> JsonObject:
        """Parse accumulated SSE data lines into a JSON object.

        Args:
            data_lines: Collected data lines for the current event.

        Returns:
            Parsed JSON dictionary.

        Raises:
            UpstreamSchemaError: If JSON parsing fails.
        """
        data_str = "\n".join(data_lines)
        try:
            parsed = json.loads(data_str)
        except json.JSONDecodeError as e:
            raise UpstreamSchemaError(f"Failed to parse SSE data as JSON: {data_str[:100]}") from e

        if not _is_json_object(parsed):
            raise UpstreamSchemaError("SSE data must decode to a JSON object")
        return parsed

    @staticmethod
    def _parse_line(
        line: str, event_type: str | None, data_lines: list[str]
    ) -> tuple[str | None, list[str]]:
        """Parse a single SSE line, updating event type and data lines.

        Args:
            line: The SSE line to parse.
            event_type: Current event type.
            data_lines: Current accumulated data lines.

        Returns:
            Updated (event_type, data_lines) tuple.
        """
        if line.startswith("event:"):
            return line[6:].strip(), data_lines
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        return event_type, data_lines


# ---------------------------------------------------------------------------
# Extracted: HTTP error classification and retry logic
# ---------------------------------------------------------------------------


class RetryHandler:
    """Error classification and retry-decision logic for HTTP requests.

    Separated from the transport client so that retry policy can be tested
    and evolved independently of connection management.
    """

    def __init__(self, logger: logging.Logger, max_retries: int) -> None:
        """Initialise retry handler.

        Args:
            logger: Logger instance for warnings and errors.
            max_retries: Maximum retry attempts before giving up.
        """
        self.logger = logger
        self.max_retries = max_retries
        self._sleep_attempt: int | None = None

    def handle_http_error(self, error: PerplexityHTTPStatusError, attempt: int) -> float:
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
            PerplexityHTTPStatusError: When not retryable or exhausted.
        """
        self._log_http_error_context(error)
        self._sleep_attempt = None
        status = error.response.status_code

        if status == HTTP_STATUS_UNAUTHORISED:
            return self._handle_401_error(error)
        if status == HTTP_STATUS_FORBIDDEN:
            return self._handle_403_error(error, attempt)
        return self._handle_retryable_error(error, attempt)

    def _handle_401_error(self, error: PerplexityHTTPStatusError) -> float:
        """Handle 401 authentication errors (never retryable)."""
        self.logger.error("HTTP 401 error (not retryable): %s", error)
        raise PerplexityHTTPStatusError(
            "Authentication failed. Token may be invalid or expired.",
            request=error.request,
            response=error.response,
        ) from error

    def _handle_403_error(self, error: PerplexityHTTPStatusError, attempt: int) -> float:
        """Handle 403 forbidden errors with retry for Cloudflare challenges."""
        if attempt < self.max_retries - 1:
            next_attempt = attempt + 1
            wait_time = get_backoff_delay(next_attempt)
            self.logger.warning(
                "HTTP 403 error (may be Cloudflare blocking), retrying in %ss (attempt %s/%s)",
                wait_time,
                next_attempt + 1,
                self.max_retries,
            )
            self._sleep_attempt = next_attempt
            return wait_time
        self.logger.error(
            "HTTP 403 error (not retryable after %s attempts): %s",
            self.max_retries,
            error,
        )
        raise PerplexityHTTPStatusError(
            "Access forbidden. Check API permissions or try again later.",
            request=error.request,
            response=error.response,
        ) from error

    def _handle_retryable_error(
        self,
        error: PerplexityHTTPStatusError,
        attempt: int,
    ) -> float:
        """Handle 429/5xx errors with backoff and Retry-After support."""
        status = error.response.status_code
        if is_retryable_error(error) and attempt < self.max_retries - 1:
            next_attempt = attempt + 1
            wait_time = get_retry_after_delay(error)
            if wait_time is None:
                wait_time = get_backoff_delay(next_attempt)
                self._sleep_attempt = next_attempt
            self.logger.warning(
                "HTTP %s error, retrying in %ss (attempt %s/%s)",
                status,
                wait_time,
                next_attempt + 1,
                self.max_retries,
            )
            return wait_time

        if status == HTTP_STATUS_TOO_MANY_REQUESTS:
            raise PerplexityHTTPStatusError(
                "Rate limit exceeded. Please wait and try again.",
                request=error.request,
                response=error.response,
            ) from error
        raise error

    def consume_sleep_attempt(self) -> int | None:
        """Return and clear the backoff attempt for the next retry sleep."""
        sleep_attempt = self._sleep_attempt
        self._sleep_attempt = None
        return sleep_attempt

    def handle_network_error(self, error: Exception, attempt: int) -> int:
        """Handle network errors, retrying if possible.

        Args:
            error: The network error.
            attempt: Current attempt number (0-indexed).

        Returns:
            Updated attempt number if retrying.

        Raises:
            PerplexityRequestError: When retries are exhausted.
        """
        if _is_request_exception(error):
            self.logger.error("Network error after %s attempts: %s", attempt + 1, error)
            raise PerplexityRequestError(str(error)) from error

        if is_retryable_error(error) and attempt < self.max_retries - 1:
            self.logger.warning(
                "Network error, retrying (attempt %s/%s): %s",
                attempt + 2,
                self.max_retries,
                error,
            )
            return attempt + 1

        self.logger.error("Network error after %s attempts: %s", attempt + 1, error)
        raise error

    def _log_http_error_context(self, error: PerplexityHTTPStatusError) -> None:
        """Log debug context for an HTTP error response.

        Captures Cloudflare headers and a redacted response body preview.

        Args:
            error: The HTTP status error to log.
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        status = error.response.status_code
        self.logger.debug("HTTP Error %s: %s", status, error)
        cf_ray = error.response.headers.get("cf-ray")
        if cf_ray:
            self.logger.debug("Cloudflare Ray ID: %s", cf_ray)
        cf_cache = error.response.headers.get("cf-cache-status")
        if cf_cache:
            self.logger.debug("Cloudflare Cache Status: %s", cf_cache)

        try:
            response_text = error.response.text[:500]
            self.logger.debug("Response body preview: %s", redact_response_text(response_text))
        except (AttributeError, TypeError):
            self.logger.debug("Could not read response body for error diagnostics")


# ---------------------------------------------------------------------------
# Main client (reduced to transport + coordination)
# ---------------------------------------------------------------------------


class SSEClient:
    """HTTP client with Server-Sent Events (SSE) streaming support.

    Uses curl_cffi with Chrome TLS fingerprint impersonation to bypass
    Cloudflare's bot protection.  SSE parsing and retry logic are
    delegated to ``SSEParser`` and ``RetryHandler`` respectively.
    """

    def __init__(
        self,
        auth: AuthContext,
        timeout: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        """Initialise SSE client.

        Args:
            auth: Authentication credentials (token and optional cookies).
            timeout: Request timeout in seconds (default from config).
            max_retries: Maximum retry attempts (default from config).
        """
        from perplexity_cli.config.defaults import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT

        self.auth = auth
        self.timeout = timeout if timeout is not None else DEFAULT_REQUEST_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        self.logger = get_logger()
        self._retry = RetryHandler(self.logger, self.max_retries)
        self._client: object | None = None

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests.

        curl_cffi sets User-Agent automatically based on the impersonated
        browser, so it is not included here.  Cookies are passed separately
        via the ``cookies`` parameter on requests rather than as a header.

        Returns:
            Dictionary of HTTP headers including authentication.
        """
        return build_perplexity_headers(
            self.auth.token,
            self.auth.cookies,
            header_extras=("text/event-stream", None),
        )

    def _get_client(self) -> object:
        """Get or create the persistent curl_cffi session.

        Returns:
            The shared Session instance with Chrome TLS impersonation.

        Raises:
            RuntimeError: If curl_cffi is not installed.
        """
        if self._client is None:
            self._client = _create_transport_session(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the persistent session if open."""
        if self._client is not None:
            _close_transport_session(self._client)
            self._client = None

    def _resolve_effective_timeout(self, json_data: JsonObject) -> tuple[bool, int]:
        """Determine the effective timeout based on query parameters.

        Deep research requests use a longer timeout (360s) to accommodate
        multi-step processing.

        Args:
            json_data: JSON request body.

        Returns:
            Tuple of (is_deep_research, effective_timeout_seconds).
        """
        params_value = json_data.get("params")
        params: JsonObject = params_value if _is_json_object(params_value) else {}
        is_deep_research = _is_deep_research_request(params)
        if is_deep_research:
            from perplexity_cli.config.defaults import DEFAULT_DEEP_RESEARCH_TIMEOUT

            effective_timeout = DEFAULT_DEEP_RESEARCH_TIMEOUT
        else:
            effective_timeout = self.timeout
        return is_deep_research, effective_timeout

    def _log_request_context(
        self,
        ctx: HttpRequestContext,
        query_mode: str = "default",
    ) -> None:
        """Log debug context for an outbound request.

        Only emits output when the logger is at DEBUG level.

        Args:
            ctx: HTTP request metadata (URL, headers, timeout).
            query_mode: ``"deep_research"`` or ``"default"``.
        """
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        self.logger.debug("API Request to: %s", redact_url(ctx.url))
        self.logger.debug("Request headers: Content-Type=%s", ctx.headers.get("Content-Type"))
        if query_mode == "deep_research":
            self.logger.debug(
                "Deep research mode detected, timeout set to %ss",
                ctx.effective_timeout,
            )

        self.logger.debug(
            "Authentication: Bearer token present=%s", bool(self.auth.token)
        )
        self._log_cookie_context()

    def _log_cookie_context(self) -> None:
        """Log cookie details for debugging Cloudflare bypass state."""
        cookies = self.auth.cookies
        if not cookies:
            self.logger.debug("Cookies: None (no Cloudflare bypass)")
            return

        cookie_names = list(cookies.keys())
        cf_cookies = [c for c in cookie_names if c.startswith("cf") or c.startswith("__cf")]
        self.logger.debug(
            "Cookies: %s total, %s Cloudflare-related",
            len(cookies),
            len(cf_cookies),
        )
        self.logger.debug("Cloudflare cookies present: %s", redact_mapping_keys(cookies))

    def _sleep_for_retry(self, wait_time: float) -> None:
        """Sleep using the canonical backoff helper or an exact upstream delay."""
        sleep_attempt = self._retry.consume_sleep_attempt()
        if sleep_attempt is not None:
            sleep_with_backoff(sleep_attempt)
            return

        threading.Event().wait(wait_time)

    def _retry_stream_error(self, error: Exception, attempt: int) -> int:
        """Translate a stream error into the next retry attempt number."""
        if isinstance(error, PerplexityHTTPStatusError):
            wait_time = self._retry.handle_http_error(error, attempt)
            self._sleep_for_retry(wait_time)
            return attempt + 1

        if isinstance(error, PerplexityRequestError) or _is_request_exception(error):
            return self._retry.handle_network_error(error, attempt)

        raise error

    def stream_post(self, url: str, json_data: JsonObject) -> Iterator[JsonObject]:
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
        ctx = HttpRequestContext(
            url=url,
            headers=headers,
            json_data=json_data,
            effective_timeout=effective_timeout,
        )
        self._log_request_context(ctx, "deep_research" if is_deep_research else "default")

        attempt = 0
        while attempt < self.max_retries:
            try:
                yield from self._execute_stream_request(ctx, attempt)
                return
            except Exception as e:
                attempt = self._retry_stream_error(e, attempt)

    def _execute_stream_request(
        self,
        ctx: HttpRequestContext,
        attempt: int,
    ) -> Iterator[JsonObject]:
        """Execute a single streaming POST request and yield parsed SSE events.

        Args:
            ctx: HTTP request metadata (URL, headers, body, timeout).
            attempt: Current attempt number (0-indexed).

        Yields:
            Parsed JSON data from each SSE message.
        """
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "Streaming POST to %s (attempt %s/%s)",
                redact_url(ctx.url),
                attempt + 1,
                self.max_retries,
            )

        client = self._get_client()
        with _open_stream_context(
            client,
            ctx,
            cookies=to_curl_cffi_cookies(self.auth.cookies),
        ) as response:
            self._log_response_headers(response)

            if not response.ok:
                raise_http_status_error(response)

            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug("Starting SSE stream parsing")

            yield from SSEParser.parse(response, self.logger)

            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug("SSE stream completed successfully")

    def _log_response_headers(self, response: _ResponseAdapter) -> None:
        """Log response status and Cloudflare headers at DEBUG level."""
        if not self.logger.isEnabledFor(logging.DEBUG):
            return

        self.logger.debug("HTTP %s %s", response.status_code, response.reason)
        for header in ("cf-ray", "cf-cache-status", "server"):
            value = response.headers.get(header)
            if value:
                label = header.replace("-", " ").title().replace("Cf ", "Cloudflare ")
                self.logger.debug("%s: %s", label, value)
