"""HTTP error handling utilities for CLI commands.

Shared policy:
- user-facing command failures exit with status code ``1``
- explicit user interruption exits with status code ``130``
- top-level unexpected failures should be logged once and routed through
  ``handle_unexpected_cli_error()``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from perplexity_cli.exit_codes import (
    HTTP_STATUS_FORBIDDEN,
    HTTP_STATUS_RATE_LIMITED,
    HTTP_STATUS_SERVER_ERROR_FLOOR,
    HTTP_STATUS_UNAUTHORIZED,
    ActionResult,
)
from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
)


@dataclass(frozen=True, slots=True)
class UnexpectedErrorContext:
    """Keyword arguments for :func:`handle_unexpected_cli_error`."""

    debug_mode: bool = False
    user_message: str = "[ERROR] An unexpected error occurred."
    log_message: str = "Unexpected error"
    include_debug_hint: bool = False

if TYPE_CHECKING:
    from perplexity_cli.envelope import ErrorCode


def raise_http_status_error(response: Any, *, method: str = "POST") -> None:
    """Convert a curl_cffi error response into a PerplexityHTTPStatusError.

    Constructs ``SimpleRequest`` and ``SimpleResponse`` objects so that
    downstream error handlers can access ``.status_code``, ``.headers``,
    and ``.text``.

    This is the single shared implementation replacing the identical
    ``_raise_http_status_error`` static methods that were previously
    duplicated across ``api/client.py``, ``threads/scraper.py``, and
    ``attachments/upload_manager.py``.

    Args:
        response: The curl_cffi Response object with a non-2xx status.
        method: HTTP method used for the request (default: ``"POST"``).

    Raises:
        PerplexityHTTPStatusError: Always raised with the converted response.
    """
    request = SimpleRequest(method=method, url=str(response.url))

    try:
        body = response.content
        text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
    except (AttributeError, TypeError, ValueError):
        text = ""

    simple_response = SimpleResponse(
        status_code=response.status_code,
        headers=dict(response.headers) if response.headers else {},
        text=text,
        request=request,
    )

    raise PerplexityHTTPStatusError(
        f"HTTP Error {response.status_code}",
        request=request,
        response=simple_response,
    )


def handle_unexpected_cli_error(
    error: Exception,
    logger: logging.Logger,
    *,
    ctx: UnexpectedErrorContext | None = None,
) -> ActionResult:
    """Build an ``ActionResult`` for an unexpected top-level CLI error.

    The caller is responsible for presenting the result (``click.echo``)
    and exiting.
    """
    resolved = ctx or UnexpectedErrorContext()
    logger.exception("%s: %s", resolved.log_message, error)

    parts: list[str] = [resolved.user_message]

    if resolved.debug_mode:
        import traceback

        debug_output = traceback.format_exc()
        if resolved.include_debug_hint:
            parts.append(f"Debug info:\n{debug_output}")
        else:
            parts.append(debug_output)
    elif resolved.include_debug_hint:
        parts.append("Run with --debug for more information.")

    return ActionResult.error("\n".join(parts), exit_code=1)


def classify_http_error(
    error: PerplexityHTTPStatusError,
) -> tuple[ErrorCode, str, str | None]:
    """Classify an HTTP error into a structured error tuple.

    Returns:
        Tuple of (error_code, human_message, fix_suggestion).
    """
    from perplexity_cli.envelope import ErrorCode

    status = error.response.status_code
    if status == HTTP_STATUS_UNAUTHORIZED:
        return (
            ErrorCode.authentication_required,
            "Authentication failed. Token may be expired.",
            "Run `pxcli auth login` to re-authenticate.",
        )
    if status == HTTP_STATUS_FORBIDDEN:
        return (
            ErrorCode.permission_denied,
            "Access forbidden. Check your permissions.",
            None,
        )
    if status == HTTP_STATUS_RATE_LIMITED:
        return (
            ErrorCode.rate_limited,
            "Rate limit exceeded. Please wait and try again.",
            "Wait a moment and retry.",
        )
    if status >= HTTP_STATUS_SERVER_ERROR_FLOOR:
        return (
            ErrorCode.network_error,
            f"Server error (HTTP {status}).",
            "Try again later.",
        )
    return (
        ErrorCode.network_error,
        f"HTTP error {status}.",
        None,
    )


def classify_network_error(
    error: PerplexityRequestError,
) -> tuple[ErrorCode, str, str | None]:
    """Classify a network error into a structured error tuple.

    Returns:
        Tuple of (error_code, human_message, fix_suggestion).
    """
    from perplexity_cli.envelope import ErrorCode

    return (
        ErrorCode.network_error,
        "Network error. Please check your internet connection.",
        "Check your internet connection.",
    )


_HTTP_ERROR_MESSAGES: dict[int, str] = {
    HTTP_STATUS_UNAUTHORIZED: "[ERROR] Authentication failed. Token may be expired.",
    HTTP_STATUS_FORBIDDEN: "[ERROR] Access forbidden. Check your permissions.",
    HTTP_STATUS_RATE_LIMITED: "[ERROR] Rate limit exceeded. Please wait and try again.",
}

_HTTP_ERROR_EXTRAS: dict[int, str] = {
    HTTP_STATUS_UNAUTHORIZED: "\nRe-authenticate with: perplexity-cli auth",
}


def handle_http_error(  # nosemgrep: boolean-flag-argument
    error: PerplexityHTTPStatusError,
    logger: logging.Logger,
    debug_mode: bool = False,
    context: str | None = None,
) -> ActionResult:
    """Build an ``ActionResult`` for an HTTP status error."""
    status = error.response.status_code
    context_msg = f" {context}" if context else ""
    logger.error("HTTP error %s%s: %s", status, context_msg, error)

    parts: list[str] = [
        _HTTP_ERROR_MESSAGES.get(status, f"[ERROR] HTTP error {status}.")
    ]
    if status in _HTTP_ERROR_EXTRAS:
        parts.append(_HTTP_ERROR_EXTRAS[status])
    if debug_mode:
        parts.append(f"Details: {error}")

    return ActionResult.error("\n".join(parts), exit_code=1)


def handle_network_error(  # nosemgrep: boolean-flag-argument
    error: PerplexityRequestError,
    logger: logging.Logger,
    debug_mode: bool = False,
    context: str | None = None,
) -> ActionResult:
    """Build an ``ActionResult`` for a network request error."""
    context_msg = f" {context}" if context else ""
    logger.error("Network error%s: %s", context_msg, error)

    parts: list[str] = [
        "[ERROR] Network error. Please check your internet connection."
    ]
    if debug_mode:
        parts.append(f"Details: {error}")

    return ActionResult.error("\n".join(parts), exit_code=1)
