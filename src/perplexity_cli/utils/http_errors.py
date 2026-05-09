"""HTTP error handling utilities for CLI commands.

Shared policy:
- user-facing command failures exit with status code ``1``
- explicit user interruption exits with status code ``130``
- top-level unexpected failures should be logged once and routed through
  ``handle_unexpected_cli_error()``
"""

import logging
import sys

import click

from perplexity_cli.utils.exceptions import PerplexityHTTPStatusError, PerplexityRequestError


def handle_unexpected_cli_error(
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
    logger.exception(f"{log_message}: {error}")
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

    logger.error(f"HTTP error {status}{context_msg}: {error}")

    if status == 401:
        click.echo("[ERROR] Authentication failed. Token may be expired.", err=True)
        click.echo("\nRe-authenticate with: perplexity-cli auth", err=True)
    elif status == 403:
        click.echo("[ERROR] Access forbidden. Check your permissions.", err=True)
    elif status == 429:
        click.echo("[ERROR] Rate limit exceeded. Please wait and try again.", err=True)
    else:
        click.echo(f"[ERROR] HTTP error {status}.", err=True)

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
    logger.error(f"Network error{context_msg}: {error}")
    click.echo("[ERROR] Network error. Please check your internet connection.", err=True)

    if debug_mode:
        click.echo(f"Details: {error}", err=True)

    sys.exit(1)
