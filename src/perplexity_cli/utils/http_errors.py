"""HTTP error handling utilities for CLI commands.

Shared policy:
- user-facing command failures exit with status code ``1``
- explicit user interruption exits with status code ``130``
- top-level unexpected failures should be logged once and routed through
  ``handle_unexpected_cli_error()``
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import click

from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    SimpleRequest,
    SimpleResponse,
)

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
    except (AttributeError, UnicodeDecodeError, TypeError, ValueError):
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


def handle_unexpected_cli_error(  # nosemgrep: too-many-parameters
    error: Exception,
    logger: logging.Logger,
    *,
    debug_mode: bool = False,
    user_message: str = "[ERROR] An unexpected error occurred.",
    log_message: str = "Unexpected error",
    include_debug_hint: bool = False,
) -> None:
    """Handle unexpected top-level CLI errors consistently.

    Policy:
    - always log the original exception once at exception level
    - always print the provided user-facing error message to stderr
    - if ``debug_mode`` is enabled, print the traceback
    - otherwise, optionally print the standard debug hint

    Exits with status code 1.
    """
    logger.exception("%s: %s", log_message, error)
    click.echo(user_message, err=True)

    if debug_mode:
        import traceback

        debug_output = traceback.format_exc()
        if include_debug_hint:
            click.echo(f"Debug info:\n{debug_output}", err=True)
        else:
            click.echo(debug_output, err=True)
    elif include_debug_hint:
        click.echo("Run with --debug for more information.", err=True)

    sys.exit(1)


def classify_http_error(
    error: PerplexityHTTPStatusError,
) -> tuple[ErrorCode, str, str | None]:
    """Classify an HTTP error into a structured error tuple.

    Returns:
        Tuple of (error_code, human_message, fix_suggestion).
    """
    from perplexity_cli.envelope import ErrorCode

    status = error.response.status_code
    if status == 401:
        return (
            ErrorCode.authentication_required,
            "Authentication failed. Token may be expired.",
            "Run `pxcli auth login` to re-authenticate.",
        )
    if status == 403:
        return (
            ErrorCode.permission_denied,
            "Access forbidden. Check your permissions.",
            None,
        )
    if status == 429:
        return (
            ErrorCode.rate_limited,
            "Rate limit exceeded. Please wait and try again.",
            "Wait a moment and retry.",
        )
    if status >= 500:
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
    401: "[ERROR] Authentication failed. Token may be expired.",
    403: "[ERROR] Access forbidden. Check your permissions.",
    429: "[ERROR] Rate limit exceeded. Please wait and try again.",
}

_HTTP_ERROR_EXTRAS: dict[int, str] = {
    401: "\nRe-authenticate with: perplexity-cli auth",
}


def handle_http_error(
    error: PerplexityHTTPStatusError,
    logger: logging.Logger,
    debug_mode: bool = False,
    context: str | None = None,
) -> None:
    """Handle HTTP status errors with user-friendly messages.

    Handles common HTTP error codes (401, 403, 429) with specific guidance.
    Falls back to generic error message for other status codes.

    Args:
        error: The PerplexityHTTPStatusError exception to handle.
        logger: Logger instance for error logging.
        debug_mode: If True, include detailed error information in output.
        context: Optional context string for more specific error messages
                (e.g., "during streaming").

    Exits with status code 1.
    """
    status = error.response.status_code
    context_msg = f" {context}" if context else ""
    logger.error("HTTP error %s%s: %s", status, context_msg, error)

    message = _HTTP_ERROR_MESSAGES.get(status, f"[ERROR] HTTP error {status}.")
    click.echo(message, err=True)
    if status in _HTTP_ERROR_EXTRAS:
        click.echo(_HTTP_ERROR_EXTRAS[status], err=True)

    if debug_mode:
        click.echo(f"Details: {error}", err=True)

    sys.exit(1)


def handle_network_error(
    error: PerplexityRequestError,
    logger: logging.Logger,
    debug_mode: bool = False,
    context: str | None = None,
) -> None:
    """Handle network request errors with user-friendly messages.

    Args:
        error: The PerplexityRequestError exception to handle.
        logger: Logger instance for error logging.
        debug_mode: If True, include detailed error information in output.
        context: Optional context string for more specific error messages
                (e.g., "during streaming").

    Exits with status code 1.
    """
    context_msg = f" {context}" if context else ""
    logger.error("Network error%s: %s", context_msg, error)
    click.echo("[ERROR] Network error. Please check your internet connection.", err=True)

    if debug_mode:
        click.echo(f"Details: {error}", err=True)

    sys.exit(1)
