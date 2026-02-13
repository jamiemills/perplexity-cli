"""HTTP error handling utilities for CLI commands."""

import logging
import sys

import click
import httpx


def handle_http_error(
    error: httpx.HTTPStatusError,
    logger: logging.Logger,
    debug_mode: bool = False,
    context: str | None = None,
) -> None:
    """Handle HTTP status errors with user-friendly messages.

    Handles common HTTP error codes (401, 403, 429) with specific guidance.
    Falls back to generic error message for other status codes.

    Args:
        error: The HTTPStatusError exception to handle.
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
    error: httpx.RequestError,
    logger: logging.Logger,
    debug_mode: bool = False,
    context: str | None = None,
) -> None:
    """Handle network request errors with user-friendly messages.

    Args:
        error: The RequestError exception to handle.
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
