"""Authentication command runners."""

import sys

import click

from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError
from perplexity_cli.utils.http_errors import handle_unexpected_cli_error
from perplexity_cli.utils.logging import get_logger


def run_auth_command(ctx_obj: dict | None, port: int) -> None:
    """Execute the auth command."""
    from perplexity_cli.auth.oauth_handler import authenticate_sync
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.utils.config import get_perplexity_base_url, get_save_cookies_enabled

    logger = get_logger()
    logger.info(f"Starting authentication on port {port}")

    base_url = get_perplexity_base_url()
    click.echo("Authenticating with Perplexity.ai...")
    click.echo(f"\nMake sure Chrome is running with --remote-debugging-port={port}")
    click.echo(f"Navigate to {base_url} and log in if needed.\n")

    try:
        logger.debug("Calling authenticate_sync")
        token, cookies = authenticate_sync(port=port)
        logger.info(f"Token and {len(cookies)} cookies extracted successfully")

        tm = TokenManager()
        tm.save_token(token, cookies=cookies)
        logger.info(f"Token and cookies saved to {tm.token_path}")

        click.echo("[OK] Authentication successful!")
        click.echo(f"[OK] Token saved to: {tm.token_path}")

        if get_save_cookies_enabled():
            click.echo(f"[OK] {len(cookies)} cookies saved (including Cloudflare cookies)")
        else:
            click.echo("[INFO] Cookies not saved (disabled in config)")
            click.echo("  To enable cookie storage: pxcli set-config save_cookies true")

        click.echo('\nYou can now use: pxcli query "<your question>"')

    except TimeoutError as e:
        logger.error(f"Authentication timeout: {e}", exc_info=True)
        click.echo(f"[ERROR] Authentication timeout: {e}", err=True)
        click.echo("\nTroubleshooting:", err=True)
        click.echo(
            f"  1. Start Chrome with: --remote-debugging-port={port}",
            err=True,
        )
        click.echo(
            "  2. Ensure Chrome is running and accessible",
            err=True,
        )
        click.echo(
            f"  3. Navigate to {base_url} in Chrome",
            err=True,
        )
        click.echo("  4. Log in with your Google account", err=True)
        click.echo("  5. Run this command again", err=True)
        sys.exit(1)

    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        click.echo(f"[ERROR] Authentication failed: {e}", err=True)
        click.echo("\nTroubleshooting:", err=True)
        click.echo(
            f"  1. Start Chrome with: --remote-debugging-port={port}",
            err=True,
        )
        click.echo(
            f"  2. Navigate to {base_url} in Chrome",
            err=True,
        )
        click.echo("  3. Log in with your Google account", err=True)
        click.echo("  4. Run this command again", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Authentication interrupted by user")
        click.echo("\n[ERROR] Authentication interrupted.", err=True)
        sys.exit(130)

    except (OSError, ConfigurationError) as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_unexpected_cli_error(
            e,
            logger,
            debug_mode=debug_mode,
            user_message=f"[ERROR] Unexpected error: {e}",
            log_message="Unexpected error during authentication",
        )


def run_logout_command() -> None:
    """Execute the logout command."""
    from perplexity_cli.auth.token_manager import TokenManager

    tm = TokenManager()

    if not tm.token_exists():
        click.echo("No stored credentials found.")
        return

    try:
        tm.clear_token()
        click.echo("[OK] Logged out successfully.")
        click.echo("[OK] Stored credentials removed.")

    except OSError as e:
        logger = get_logger()
        handle_unexpected_cli_error(
            e,
            logger,
            user_message=f"[ERROR] Error during logout: {e}",
            log_message="Error during logout",
        )
