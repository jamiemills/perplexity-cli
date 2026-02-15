"""Authentication utilities for CLI commands."""

import logging
import sys

import click

from perplexity_cli.auth.token_manager import TokenManager


def load_or_prompt_token(
    tm: TokenManager,
    logger: logging.Logger,
    command_context: str = "operation",
) -> tuple[str, dict[str, str]]:
    """Load authentication token or prompt user to authenticate.

    Attempts to load an existing token from disk. If not found or invalid,
    prompts the user to authenticate and exits with helpful message.

    Args:
        tm: TokenManager instance to use for loading.
        logger: Logger instance for logging authentication attempts.
        command_context: Context string for error messages (e.g., "query").

    Returns:
        Tuple of (token, cookies) where:
            - token: The authentication token string
            - cookies: Dictionary of browser cookies {name: value}

    Exits with status 1 if token cannot be loaded.
    """
    token, cookies = tm.load_token()

    if not token:
        click.echo("[ERROR] Not authenticated.", err=True)
        click.echo(
            "\nPlease authenticate first with: pxcli auth",
            err=True,
        )
        logger.warning(f"Attempted {command_context} without authentication")
        sys.exit(1)

    return token, cookies


def load_token_optional(
    tm: TokenManager,
    logger: logging.Logger,
) -> tuple[str | None, dict[str, str] | None]:
    """Load authentication token if available, otherwise return None values.

    Attempts to load an existing token from disk. Unlike load_or_prompt_token(),
    this function does not prompt the user or exit if no token is found.
    Used by commands that can operate with or without authentication.

    Args:
        tm: TokenManager instance to use for loading.
        logger: Logger instance for logging authentication attempts.

    Returns:
        Tuple of (token, cookies) where:
            - token: The authentication token string, or None if not found
            - cookies: Dictionary of browser cookies {name: value}, or None if not found

    Does not exit or prompt if token is unavailable.
    """
    token, cookies = tm.load_token()

    if token:
        logger.debug("Authentication token loaded")
    else:
        logger.debug("No authentication token found; proceeding without authentication")

    return token, cookies
