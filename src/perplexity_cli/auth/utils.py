"""Authentication utilities for CLI commands."""

import logging
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.exit_codes import ActionResult
from perplexity_cli.utils.exceptions import AuthenticationError
from perplexity_cli.utils.session_token import extract_session_token

__all__ = ["extract_session_token"]


def load_or_prompt_token(
    tm: TokenManager,
    logger: logging.Logger,
    command_context: str = "operation",
) -> "tuple[str, dict[str, str] | None] | ActionResult":

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
        logger.warning("Authentication state invalid during %s: %s", command_context, e)
        return ActionResult.error("\n".join([f"[ERROR] Authentication error: {e}","\nPlease authenticate again with: pxcli auth login"]), exit_code=1)

    if not token:
        logger.warning("Attempted %s without authentication", command_context)
        return ActionResult.error("\n".join(["[ERROR] Not authenticated.","\nPlease authenticate first with: pxcli auth login"]), exit_code=1)

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
        logger.warning(  # nosemgrep: python-logger-credential-disclosure
            "Stored authentication is unusable; proceeding without token: %s", e
        )
        return None, None

    if token:
        logger.debug("Authentication token loaded")
    else:
        logger.debug("No authentication token found; proceeding without authentication")

    return token, cookies
