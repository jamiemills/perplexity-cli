"""Authentication command runners."""

import sys

import click

from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error
from perplexity_cli.runners._utils import resolve_json_flag
from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError
from perplexity_cli.utils.http_errors import handle_unexpected_cli_error
from perplexity_cli.utils.logging import get_logger

_AUTH_LOGIN_COMMAND = "pxcli auth login"


def _print_auth_troubleshooting(port: int, base_url: str) -> None:
    """Print authentication troubleshooting steps."""
    click.echo("\nTroubleshooting:", err=True)
    click.echo(f"  1. Start Chrome with: --remote-debugging-port={port}", err=True)
    click.echo("  2. Ensure Chrome is running and accessible", err=True)
    click.echo(f"  3. Navigate to {base_url} in Chrome", err=True)
    click.echo("  4. Log in with your Google account", err=True)
    click.echo("  5. Run this command again", err=True)


def _handle_auth_success(token, cookies, json_mode, include_schema) -> None:
    """Handle successful authentication output."""
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.utils.config import get_save_cookies_enabled

    tm = TokenManager()
    tm.save_token(token, cookies=cookies)
    get_logger().info("Token and cookies saved to %s", tm.token_path)

    if json_mode:
        env = success_envelope(
            _AUTH_LOGIN_COMMAND,
            {"token_path": str(tm.token_path), "cookies_stored": len(cookies)},
        )
        write_envelope(env, include_schema=include_schema)
        return

    click.echo("[OK] Authentication successful!")
    click.echo(f"[OK] Token saved to: {tm.token_path}")

    if get_save_cookies_enabled():
        click.echo(f"[OK] {len(cookies)} cookies saved (including Cloudflare cookies)")
    else:
        click.echo("[INFO] Cookies not saved (disabled in config)")
        click.echo("  To enable cookie storage: pxcli config set save_cookies true")

    click.echo('\nYou can now use: pxcli query "<your question>"')


def _resolve_ctx_flags(ctx_obj: dict | None) -> tuple[bool, bool, bool]:
    """Extract json_mode, include_schema, and debug_mode from context."""
    json_mode = ctx_obj.get("json", False) if ctx_obj else False
    include_schema = ctx_obj.get("schema", False) if ctx_obj else False
    debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
    return json_mode, include_schema, debug_mode


def run_auth_command(ctx_obj: dict | None, port: int) -> None:
    """Execute the auth command."""
    from perplexity_cli.utils.config import get_perplexity_base_url

    logger = get_logger()
    json_mode, include_schema, debug_mode = _resolve_ctx_flags(ctx_obj)
    logger.info("Starting authentication on port %s", port)

    base_url = get_perplexity_base_url()
    if not json_mode:
        click.echo("Authenticating with Perplexity.ai...")
        click.echo(f"\nMake sure Chrome is running with --remote-debugging-port={port}")
        click.echo(f"Navigate to {base_url} and log in if needed.\n")

    try:
        _execute_auth(port, json_mode, include_schema, base_url, debug_mode, logger)
    except KeyboardInterrupt:
        logger.info("Authentication interrupted by user")
        click.echo("\n[ERROR] Authentication interrupted.", err=True)
        sys.exit(130)


def _execute_auth(  # nosemgrep: too-many-parameters
    port, json_mode, include_schema, base_url, debug_mode, logger
) -> None:
    """Perform authentication and handle domain-specific errors."""
    from perplexity_cli.auth.oauth_handler import authenticate_sync

    try:
        logger.debug("Calling authenticate_sync")
        token, cookies = authenticate_sync(port=port)
        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "Token and %s cookies extracted successfully", len(cookies)
        )
        _handle_auth_success(token, cookies, json_mode, include_schema)
    except (TimeoutError, AuthenticationError) as e:
        if json_mode:
            handle_error(e, command=_AUTH_LOGIN_COMMAND, json_mode=True)
        logger.debug("Authentication failed: %s", e, exc_info=True)
        click.echo(f"[ERROR] Authentication failed: {e}", err=True)
        _print_auth_troubleshooting(port, base_url)
        sys.exit(1)
    except (OSError, ConfigurationError) as e:
        if json_mode:
            handle_error(e, command=_AUTH_LOGIN_COMMAND, json_mode=True)
        handle_unexpected_cli_error(
            e,
            logger,
            debug_mode=debug_mode,
            user_message=f"[ERROR] Unexpected error: {e}",
            log_message="Unexpected error during authentication",
        )


def _resolve_logout_ctx(json_mode: bool | None) -> tuple[bool, bool]:
    """Resolve json_mode and include_schema from context."""
    ctx = click.get_current_context(silent=True)
    ctx_obj = ctx.obj if ctx else {}
    resolved_json = resolve_json_flag(json_mode, ctx_obj)
    include_schema = ctx_obj.get("schema", False) if ctx_obj else False
    return resolved_json, include_schema


def _logout_emit(  # nosemgrep: boolean-flag-argument
    json_mode: bool, include_schema: bool, existed: bool
) -> None:
    """Emit logout result in the appropriate format."""
    if json_mode:
        env = success_envelope("pxcli auth logout", {"credentials_existed": existed})
        write_envelope(env, include_schema=include_schema)
        return
    if not existed:
        click.echo("No stored credentials found.")
    else:
        click.echo("[OK] Logged out successfully.")
        click.echo("[OK] Stored credentials removed.")


def run_logout_command(*, json_mode: bool | None = None) -> None:
    """Execute the logout command."""
    from perplexity_cli.auth.token_manager import TokenManager

    resolved_json, include_schema = _resolve_logout_ctx(json_mode)
    tm = TokenManager()

    if not tm.token_exists():
        _logout_emit(resolved_json, include_schema, existed=False)
        return

    try:
        tm.clear_token()
        _logout_emit(resolved_json, include_schema, existed=True)
    except OSError as e:
        if resolved_json:
            handle_error(e, command="pxcli auth logout", json_mode=True)
        logger = get_logger()
        handle_unexpected_cli_error(
            e,
            logger,
            user_message=f"[ERROR] Error during logout: {e}",
            log_message="Error during logout",
        )
