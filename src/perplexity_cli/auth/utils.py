"""Authentication utilities for CLI commands."""

import json
import logging
import sys

import click

from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.utils.exceptions import AuthenticationError


def extract_session_token(raw_token: str) -> str:
    """Extract a usable session token from the raw decrypted token data.

    The stored token may be either a raw JWT string or a JSON object
    containing ``{"user": {"accessToken": "..."}}``.  This function
    normalises both formats to a plain token string suitable for use
    as a session cookie or Bearer token.

    Args:
        raw_token: The decrypted token string (may be JSON or plain).

    Returns:
        A plain session token string.

    Raises:
        AuthenticationError: If the token structure is malformed.
    """
    try:
        token_data = json.loads(raw_token)
    except json.JSONDecodeError:
        # Not JSON — treat as a raw token string
        return raw_token

    if not isinstance(token_data, dict):
        raise AuthenticationError("Stored token has invalid session data format")

    user_data = token_data.get("user")
    if user_data is None:
        return raw_token

    if not isinstance(user_data, dict):
        raise AuthenticationError("Stored token has invalid session user data")

    access_token = user_data.get("accessToken")
    if access_token is None:
        return raw_token

    if not isinstance(access_token, str) or not access_token:
        raise AuthenticationError("Stored token has invalid access token data")

    return access_token


def load_or_prompt_token(
    tm: TokenManager,
    logger: logging.Logger,
    command_context: str = "operation",
) -> tuple[str, dict[str, str] | None]:
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
            - cookies: Dictionary of browser cookies {name: value}, if available

    Exits with status 1 if token cannot be loaded.
    """
    try:
        token, cookies = tm.load_token()
    except AuthenticationError as e:
        click.echo(f"[ERROR] Authentication error: {e}", err=True)
        click.echo("\nPlease authenticate again with: pxcli auth", err=True)
        logger.warning(f"Authentication state invalid during {command_context}: {e}")
        sys.exit(1)

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
    try:
        token, cookies = tm.load_token()
    except AuthenticationError as e:
        logger.warning(f"Stored authentication is unusable; proceeding without token: {e}")
        return None, None

    if token:
        logger.debug("Authentication token loaded")
    else:
        logger.debug("No authentication token found; proceeding without authentication")

    return token, cookies
