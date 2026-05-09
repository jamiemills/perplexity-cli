"""Shared command orchestration helpers for the CLI."""

import asyncio
import os
import stat
import sys
from datetime import datetime
from importlib.resources import files
from pathlib import Path

import click

from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)
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


def run_configure_command(style: str) -> None:
    """Execute the configure command."""
    from perplexity_cli.utils.style_manager import StyleManager

    sm = StyleManager()

    try:
        sm.save_style(style)
        click.echo("[OK] Style configured successfully.")
        click.echo("[OK] Style will be applied to all future queries.")
        click.echo("\nStyle preview:")
        click.echo(f"  {style}")
    except ValueError as e:
        click.echo(f"[ERROR] Invalid style: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        click.echo(f"[ERROR] Failed to save style: {e}", err=True)
        sys.exit(1)


def run_view_style_command() -> None:
    """Execute the view-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    sm = StyleManager()

    try:
        style = sm.load_style()

        if style is None:
            click.echo("No style configured.")
            click.echo("\nSet a style with:")
            click.echo("  perplexity-cli configure <STYLE>")
        else:
            click.echo("Current style:")
            click.echo("-" * 50)
            click.echo(style)
            click.echo("-" * 50)
    except OSError as e:
        click.echo(f"[ERROR] Error reading style: {e}", err=True)
        sys.exit(1)


def run_clear_style_command() -> None:
    """Execute the clear-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    sm = StyleManager()

    try:
        style = sm.load_style()

        if style is None:
            click.echo("No style is currently configured.")
            return

        sm.clear_style()
        click.echo("[OK] Style cleared successfully.")
        click.echo("[OK] Queries will no longer include a style prompt.")

    except OSError as e:
        click.echo(f"[ERROR] Error clearing style: {e}", err=True)
        sys.exit(1)


def run_set_config_command(key: str, value: str) -> None:
    """Execute the set-config command."""
    from perplexity_cli.utils.config import clear_feature_config_cache, set_feature

    logger = get_logger()

    try:
        bool_value = value.lower() == "true"
        set_feature(key, bool_value)
        clear_feature_config_cache()

        click.echo(f"[OK] Configuration updated: {key} = {bool_value}")
        logger.info(f"Configuration updated: {key} = {bool_value}")

        if key == "save_cookies" and bool_value:
            click.echo("\n[INFO] Cookie storage enabled.")
            click.echo("  Re-authenticate to save cookies: pxcli auth")
        elif key == "save_cookies" and not bool_value:
            click.echo("\n[INFO] Cookie storage disabled.")
            click.echo("  Only JWT token will be saved on next authentication.")
        elif key == "debug_mode" and bool_value:
            click.echo("\n[INFO] Debug mode enabled.")
            click.echo("  All commands will now log at DEBUG level.")
        elif key == "debug_mode" and not bool_value:
            click.echo("\n[INFO] Debug mode disabled.")
            click.echo("  Use --debug flag for one-time debug output.")

    except ConfigurationError as e:
        click.echo(f"[ERROR] Failed to update configuration: {e}", err=True)
        logger.error(f"Configuration update failed: {e}", exc_info=True)
        sys.exit(1)


def run_show_config_command() -> None:
    """Execute the show-config command."""
    from perplexity_cli.utils.config import get_feature_config, get_feature_config_path

    logger = get_logger()

    try:
        config = get_feature_config()
        config_path = get_feature_config_path()

        click.echo("Perplexity CLI Configuration")
        click.echo("=" * 40)
        click.echo(f"Config file: {config_path}")
        click.echo()

        click.echo("Feature Toggles:")
        click.echo(f"  save_cookies: {config.save_cookies}")
        click.echo(f"  debug_mode:   {config.debug_mode}")
        click.echo()

        env_overrides = []
        if "PERPLEXITY_SAVE_COOKIES" in os.environ:
            env_overrides.append(
                f"  PERPLEXITY_SAVE_COOKIES={os.environ['PERPLEXITY_SAVE_COOKIES']}"
            )
        if "PERPLEXITY_DEBUG_MODE" in os.environ:
            env_overrides.append(f"  PERPLEXITY_DEBUG_MODE={os.environ['PERPLEXITY_DEBUG_MODE']}")

        if env_overrides:
            click.echo("Environment Overrides:")
            for override in env_overrides:
                click.echo(override)
            click.echo()

        click.echo("To change settings:")
        click.echo("  pxcli set-config save_cookies true|false")
        click.echo("  pxcli set-config debug_mode true|false")

        logger.debug("Configuration displayed successfully")

    except ConfigurationError as e:
        click.echo(f"[ERROR] Failed to load configuration: {e}", err=True)
        logger.error(f"Configuration display failed: {e}", exc_info=True)
        sys.exit(1)


def run_doctor_security_command() -> None:
    """Execute the doctor security command."""
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.utils.config import get_feature_config

    tm = TokenManager()
    cache_manager = ThreadCacheManager()
    feature_config = get_feature_config()

    def describe_permissions(path: Path | None, expected: int) -> str:
        if path is None or not path.exists():
            return "not present"

        actual = stat.S_IMODE(path.stat().st_mode)
        if actual == expected:
            return f"secure ({oct(actual)})"
        return f"insecure ({oct(actual)}; expected {oct(expected)})"

    click.echo("Perplexity CLI Security")
    click.echo("=" * 40)
    click.echo("Storage backend: machine-bound encrypted file storage")
    click.echo(
        "Threat model: protects against casual file copying between machines, not against "
        "other local processes or users that can already read these files"
    )
    click.echo()
    click.echo(f"Token file: {tm.token_path}")
    click.echo(
        f"Token file permissions: {describe_permissions(tm.token_path, tm.SECURE_PERMISSIONS)}"
    )
    click.echo(f"Thread cache file: {cache_manager.cache_path}")
    click.echo(
        "Thread cache permissions: "
        f"{describe_permissions(cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS)}"
    )
    click.echo(f"Cookie storage enabled: {feature_config.save_cookies}")
    if feature_config.save_cookies:
        click.echo(
            "Cookie storage warning: browser cookies are sensitive and should only be stored "
            "when needed for Cloudflare/session reuse"
        )


def run_show_skill_command() -> None:
    """Execute the show-skill command."""
    try:
        skill_content = (
            files("perplexity_cli.resources").joinpath("skill.md").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, AttributeError):
        skill_content = "Agent Skill definition not available. Run 'perplexity-cli --help' for usage information."
    click.echo(skill_content)


def run_status_command(verify: bool) -> None:
    """Execute the status command."""
    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.auth.token_manager import TokenManager

    logger = get_logger()
    tm = TokenManager()

    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)

    if not tm.token_exists():
        click.echo("Status: [ERROR] Not authenticated")
        click.echo("\nAuthenticate with: pxcli auth")
        return

    try:
        token, cookies = tm.load_token()
        if not token:
            click.echo("Status: [ERROR] Not authenticated")
            return

        click.echo("Status: [OK] Authenticated")
        click.echo(f"Token file: {tm.token_path}")
        click.echo(f"Token length: {len(token)} characters")
        if cookies:
            click.echo(f"Cookies: {len(cookies)} stored")

        try:
            stat_result = tm.token_path.stat()
            modified_time = datetime.fromtimestamp(stat_result.st_mtime)
            click.echo(f"Token last modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}")
        except OSError:
            pass

        if not verify:
            click.echo("\n[INFO] Live verification not run")
            click.echo("Use 'pxcli status --verify' to test the current token against the API.")
            return

        try:
            logger.debug("Verifying token validity")
            with PerplexityAPI(token=token, cookies=cookies, timeout=10) as api:
                test_answer = api.get_complete_answer("test")
            if test_answer and len(test_answer.text) > 0:
                click.echo("\n[OK] Token is valid and working")
                logger.info("Token verification successful")
            else:
                click.echo("\n[INFO] Token verification returned empty response")
                logger.warning("Token verification returned empty response")
        except PerplexityHTTPStatusError as e:
            if e.response.status_code == 401:
                click.echo("\n[ERROR] Token is invalid or expired")
                logger.warning("Token verification failed: 401 Unauthorized")
            else:
                click.echo(f"\n[INFO] Token verification failed (HTTP {e.response.status_code})")
                logger.warning(f"Token verification failed: HTTP {e.response.status_code}")
        except (PerplexityRequestError, UpstreamSchemaError, AuthenticationError) as e:
            click.echo("\n[INFO] Token verification failed (unable to test)")
            logger.debug(f"Token verification error: {e}", exc_info=True)

    except AuthenticationError as e:
        click.echo("Status: [INFO] Token file has insecure permissions")
        click.echo(f"Error: {e}")
        click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
        logger.error(f"Token file has insecure permissions: {e}")


def run_export_threads_command(
    ctx_obj: dict | None,
    from_date: str | None,
    to_date: str | None,
    output: Path | None,
    force_refresh: bool,
    clear_cache: bool,
) -> None:
    """Execute the export-threads command."""
    from dateutil import parser as dateutil_parser

    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.threads.exporter import write_threads_csv
    from perplexity_cli.threads.scraper import ThreadScraper
    from perplexity_cli.utils.config import get_rate_limiting_config
    from perplexity_cli.utils.rate_limiter import RateLimiter

    logger = get_logger()
    logger.info("Starting thread export")
    click.echo("Exporting threads from Perplexity.ai library...")

    tm = TokenManager()
    token, cookies = tm.load_token()
    if not token:
        click.echo("[ERROR] Not authenticated.", err=True)
        click.echo("\nPlease authenticate first with: pxcli auth", err=True)
        logger.warning("Export attempted without authentication")
        sys.exit(1)

    rate_limit_config = get_rate_limiting_config()
    rate_limiter = None
    if rate_limit_config.enabled:
        rate_limiter = RateLimiter(
            requests_per_period=rate_limit_config.requests_per_period,
            period_seconds=rate_limit_config.period_seconds,
        )
        logger.info(
            f"Rate limiting enabled: {rate_limit_config.requests_per_period} requests per "
            f"{rate_limit_config.period_seconds} seconds"
        )

    cache_manager = ThreadCacheManager()
    if clear_cache:
        if cache_manager.cache_exists():
            cache_manager.clear_cache()
            click.echo("[OK] Cache cleared")
            logger.info("Cache cleared by user")
        else:
            click.echo("[INFO] No cache file to clear")

    if from_date or to_date:
        try:
            if from_date:
                dateutil_parser.parse(from_date)
            if to_date:
                dateutil_parser.parse(to_date)
        except ValueError as e:
            click.echo(f"[ERROR] Invalid date format: {e}", err=True)
            click.echo("Please use YYYY-MM-DD format (e.g., 2025-12-23)", err=True)
            sys.exit(1)

    try:
        scraper = ThreadScraper(
            token=token,
            cookies=cookies,
            rate_limiter=rate_limiter,
            cache_manager=cache_manager,
            force_refresh=force_refresh,
        )

        def update_progress(current: int, total: int) -> None:
            click.echo(f"\rExtracting {current} threads...", nl=False)

        async def run_scrape() -> list:
            return await scraper.scrape_all_threads(
                from_date=from_date,
                to_date=to_date,
                progress_callback=update_progress,
            )

        threads = asyncio.run(run_scrape())
        click.echo()

        if not threads:
            click.echo("\n[ERROR] No threads found matching criteria.", err=True)
            if from_date or to_date:
                click.echo(
                    f"Date range: {from_date or 'beginning'} to {to_date or 'end'}",
                    err=True,
                )
            sys.exit(1)

        output_path = write_threads_csv(threads, output)
        logger.info(f"Exported {len(threads)} threads to {output_path}")

        click.echo("\n[OK] Export complete")
        click.echo(f"[OK] Exported {len(threads)} threads")
        if from_date or to_date:
            click.echo(
                f"[OK] Filtered by date range: {from_date or 'beginning'} to {to_date or 'end'}"
            )
        click.echo(f"[OK] Saved to: {output_path.resolve()}")

    except (AuthenticationError, PerplexityRequestError, UpstreamSchemaError, ValueError) as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        click.echo(f"\n[ERROR] Export failed: {e}", err=True)
        if "Authentication failed" in str(e):
            click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
            click.echo("  perplexity-cli auth", err=True)
        sys.exit(1)

    except RateLimitError as e:
        logger.error(f"Export rate limited: {e}", exc_info=True)
        click.echo(f"\n[ERROR] Export failed: {e}", err=True)
        sys.exit(1)

    except PerplexityHTTPStatusError as e:
        status = e.response.status_code
        logger.error(f"HTTP error {status}: {e}")
        if status == 401:
            click.echo("[ERROR] Authentication failed. Token may be expired.", err=True)
            click.echo("\nRe-authenticate with: perplexity-cli auth", err=True)
        elif status == 403:
            click.echo("[ERROR] Access forbidden. Check your permissions.", err=True)
        elif status == 429:
            click.echo("[ERROR] Rate limit exceeded. Please wait and try again later.", err=True)
        else:
            click.echo(f"[ERROR] HTTP error {status}.", err=True)
            if ctx_obj and ctx_obj.get("debug", False):
                click.echo(f"Details: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Export interrupted by user")
        click.echo("\n[ERROR] Export interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_unexpected_cli_error(
            e,
            logger,
            debug_mode=debug_mode,
            user_message=f"\n[ERROR] Unexpected error: {e}",
            log_message="Unexpected error during export",
        )
