"""Authentication command runners."""

from __future__ import annotations

import sys
from typing import TypeGuard

import click

from perplexity_cli._types import DebugMode, OutputFormat, SchemaInclusion
from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error
from perplexity_cli.runners._utils import resolve_json_flag
from perplexity_cli.utils.exceptions import AuthenticationError, ConfigurationError
from perplexity_cli.utils.http_errors import handle_unexpected_cli_error
from perplexity_cli.utils.logging import get_logger

_AUTH_LOGIN_COMMAND = "pxcli auth login"


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    """TypeGuard: value is a dictionary with string keys."""
    return isinstance(value, dict)


def _ctx_to_dict() -> dict[str, object]:
    """Extract the Click context object as a typed dict."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return {}
    raw: object = ctx.obj
    if _is_str_dict(raw):
        return raw
    return {}


def _print_auth_troubleshooting(port: int, base_url: str) -> None:
    """Print authentication troubleshooting steps."""
    click.echo("\nTroubleshooting:", err=True)
    click.echo(f"  1. Start Chrome with: --remote-debugging-port={port}", err=True)
    click.echo("  2. Ensure Chrome is running and accessible", err=True)
    click.echo(f"  3. Navigate to {base_url} in Chrome", err=True)
    click.echo("  4. Log in with your Google account", err=True)
    click.echo("  5. Run this command again", err=True)


def _handle_auth_success(
    token: str,
    cookies: dict[str, str],
    output_format: OutputFormat,
    include_schema: SchemaInclusion,
) -> None:
    """Handle successful authentication output."""
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.utils.config import get_save_cookies_enabled

    tm = TokenManager()
    tm.save_token(token, cookies=cookies)
    get_logger().info("Token and cookies saved to %s", tm.token_path)

    if output_format == "json":
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


def _resolve_ctx_flags(ctx_obj: object) -> tuple[bool, bool, bool]:
    """Extract json_mode, include_schema, and debug_mode from context."""
    ctx_dict = (
        _ctx_to_dict() if ctx_obj is None else ctx_obj if _is_str_dict(ctx_obj) else _ctx_to_dict()
    )
    val_json: object = ctx_dict.get("json", False)
    val_schema: object = ctx_dict.get("schema", False)
    val_debug: object = ctx_dict.get("debug", False)
    return bool(val_json), bool(val_schema), bool(val_debug)


def run_auth_command(ctx_obj: object, port: int) -> None:
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
        _execute_auth(port, (json_mode, include_schema, debug_mode), base_url)
    except KeyboardInterrupt:
        logger.info("Authentication interrupted by user")


def _execute_auth(
    port: int,
    ctx_flags: tuple[bool, bool, bool],
    base_url: str,
) -> None:
    """Perform authentication and handle domain-specific errors."""
    json_mode, include_schema, debug_mode = ctx_flags
    output_format: OutputFormat = "json" if json_mode else "human"
    schema_inclusion: SchemaInclusion = "with_schema" if include_schema else "no_schema"
    debug_level: DebugMode = "debug" if debug_mode else "normal"
    from perplexity_cli.auth.oauth_handler import authenticate_sync

    logger = get_logger()

    try:
        logger.debug("Calling authenticate_sync")
        token, cookies = authenticate_sync(port=port)
        logger.info(
            "Token and %s cookies extracted successfully", len(cookies)
        )
        _handle_auth_success(token, cookies, output_format, schema_inclusion)
    except (TimeoutError, AuthenticationError) as e:
        if output_format == "json":
            handle_error(e, _AUTH_LOGIN_COMMAND, output_format="json")
        logger.debug("Authentication failed: %s", e, exc_info=True)
        click.echo(f"[ERROR] Authentication failed: {e}", err=True)
        _print_auth_troubleshooting(port, base_url)
        sys.exit(1)
    except (OSError, ConfigurationError) as e:
        if output_format == "json":
            handle_error(e, _AUTH_LOGIN_COMMAND, output_format="json")
        handle_unexpected_cli_error(
            e,
            logger,
            debug_mode=debug_level,
            message_tuple=(f"[ERROR] Unexpected error: {e}", "Unexpected error during authentication", False),
        )


def _resolve_logout_ctx(
    json_mode: bool | None,
) -> tuple[OutputFormat, SchemaInclusion]:
    """Resolve json_mode and include_schema from context."""
    ctx_dict = _ctx_to_dict()
    resolved_json = resolve_json_flag(json_mode, ctx_dict)
    val_schema: object = ctx_dict.get("schema", False)
    return (
        "json" if resolved_json else "human",
        "with_schema" if bool(val_schema) else "no_schema",
    )


def _logout_emit(
    output_format: OutputFormat,
    include_schema: SchemaInclusion,
    existed: bool,
) -> None:
    """Emit logout result in the appropriate format."""
    if output_format == "json":
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
        if resolved_json == "json":
            handle_error(e, "pxcli auth logout", output_format="json")
        logger = get_logger()
        handle_unexpected_cli_error(
            e,
            logger,
            message_tuple=(f"[ERROR] Error during logout: {e}", "Error during logout", False),
        )
