"""Configuration and style command runners."""

import os
import sys

import click

from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error
from perplexity_cli.utils.exceptions import ConfigurationError
from perplexity_cli.utils.logging import get_logger


def _get_include_schema() -> bool:
    """Read include_schema flag from Click context."""
    ctx = click.get_current_context(silent=True)
    ctx_obj = ctx.obj if ctx else {}
    return ctx_obj.get("schema", False) if ctx_obj else False


def _get_json_mode_from_ctx() -> bool:
    """Read json_mode flag from Click context."""
    ctx = click.get_current_context(silent=True)
    ctx_obj = ctx.obj if ctx else {}
    return ctx_obj.get("json", False) if ctx_obj else False


def _handle_style_error(e: Exception, json_mode: bool, command: str, message: str) -> None:
    """Handle style command errors uniformly."""
    if json_mode:
        handle_error(e, command=command, json_mode=True)
    click.echo(f"[ERROR] {message}: {e}", err=True)
    sys.exit(1)


def run_configure_command(style: str, *, json_mode: bool | None = None) -> None:
    """Execute the configure command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    sm = StyleManager()

    try:
        sm.save_style(style)
        if json_mode:
            env = success_envelope("pxcli style set", {"style": style})
            write_envelope(env, include_schema=_get_include_schema())
            return
        click.echo("[OK] Style configured successfully.")
        click.echo("[OK] Style will be applied to all future queries.")
        click.echo("\nStyle preview:")
        click.echo(f"  {style}")
    except (ValueError, OSError) as e:
        msg = "Invalid style" if isinstance(e, ValueError) else "Failed to save style"
        _handle_style_error(e, json_mode, "pxcli style set", msg)


def _output_view_style(style) -> None:
    """Print style in human-readable format."""
    if style is None:
        click.echo("No style configured.")
        click.echo("\nSet a style with:")
        click.echo("  perplexity-cli configure <STYLE>")
    else:
        click.echo("Current style:")
        click.echo("-" * 50)
        click.echo(style)
        click.echo("-" * 50)


def run_view_style_command(*, json_mode: bool | None = None) -> None:
    """Execute the view-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    sm = StyleManager()

    try:
        style = sm.load_style()
        if json_mode:
            env = success_envelope("pxcli style show", {"style": style})
            write_envelope(env, include_schema=_get_include_schema())
            return
        _output_view_style(style)
    except OSError as e:
        _handle_style_error(e, json_mode, "pxcli style show", "Error reading style")


def _execute_clear_style(sm, json_mode) -> None:
    """Perform the clear style operation and output results."""
    style = sm.load_style()
    had_style = style is not None

    if had_style:
        sm.clear_style()

    if json_mode:
        env = success_envelope("pxcli style clear", {"had_style": had_style})
        write_envelope(env, include_schema=_get_include_schema())
        return

    if not had_style:
        click.echo("No style is currently configured.")
        return

    click.echo("[OK] Style cleared successfully.")
    click.echo("[OK] Queries will no longer include a style prompt.")


def run_clear_style_command(*, json_mode: bool | None = None) -> None:
    """Execute the clear-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    sm = StyleManager()

    try:
        _execute_clear_style(sm, json_mode)
    except OSError as e:
        _handle_style_error(e, json_mode, "pxcli style clear", "Error clearing style")


_CONFIG_CHANGE_MESSAGES: dict[tuple[str, bool], tuple[str, str]] = {
    ("save_cookies", True): (
        "[INFO] Cookie storage enabled.",
        "  Re-authenticate to save cookies: pxcli auth",
    ),
    ("save_cookies", False): (
        "[INFO] Cookie storage disabled.",
        "  Only JWT token will be saved on next authentication.",
    ),
    ("debug_mode", True): (
        "[INFO] Debug mode enabled.",
        "  All commands will now log at DEBUG level.",
    ),
    ("debug_mode", False): (
        "[INFO] Debug mode disabled.",
        "  Use --debug flag for one-time debug output.",
    ),
}


def _print_config_change_message(key: str, bool_value: bool) -> None:
    """Print contextual message after a configuration change."""
    msgs = _CONFIG_CHANGE_MESSAGES.get((key, bool_value))
    if msgs:
        click.echo(f"\n{msgs[0]}")
        click.echo(msgs[1])


def run_set_config_command(key: str, value: str, *, json_mode: bool | None = None) -> None:
    """Execute the set-config command."""
    from perplexity_cli.utils.config import clear_feature_config_cache, set_feature

    logger = get_logger()

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    try:
        bool_value = value.lower() == "true"
        set_feature(key, bool_value)
        clear_feature_config_cache()

        if json_mode:
            env = success_envelope(
                "pxcli config set",
                {
                    "key": key,
                    "value": bool_value,
                },
            )
            write_envelope(env, include_schema=_get_include_schema())
            return

        click.echo(f"[OK] Configuration updated: {key} = {bool_value}")
        logger.info("Configuration updated: %s = %s", key, bool_value)
        _print_config_change_message(key, bool_value)

    except ConfigurationError as e:
        if json_mode:
            handle_error(e, command="pxcli config set", json_mode=True)
        click.echo(f"[ERROR] Failed to update configuration: {e}", err=True)
        logger.error("Configuration update failed: %s", e, exc_info=True)
        sys.exit(1)


_ENV_OVERRIDE_KEYS = ("PERPLEXITY_SAVE_COOKIES", "PERPLEXITY_DEBUG_MODE")


def _collect_env_overrides(prefix: str = "") -> list[str]:
    """Collect active environment variable overrides."""
    return [f"{prefix}{key}={os.environ[key]}" for key in _ENV_OVERRIDE_KEYS if key in os.environ]


def _output_config_text(config, config_path, env_overrides: list[str]) -> None:
    """Print human-readable configuration output."""
    click.echo("Perplexity CLI Configuration")
    click.echo("=" * 40)
    click.echo(f"Config file: {config_path}")
    click.echo()
    click.echo("Feature Toggles:")
    click.echo(f"  save_cookies: {config.save_cookies}")
    click.echo(f"  debug_mode:   {config.debug_mode}")
    click.echo()

    if env_overrides:
        click.echo("Environment Overrides:")
        for override in env_overrides:
            click.echo(override)
        click.echo()

    click.echo("To change settings:")
    click.echo("  pxcli set-config save_cookies true|false")
    click.echo("  pxcli set-config debug_mode true|false")


def run_show_config_command(*, json_mode: bool | None = None) -> None:
    """Execute the show-config command."""
    from perplexity_cli.utils.config import get_feature_config, get_feature_config_path

    logger = get_logger()

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    try:
        config = get_feature_config()
        config_path = get_feature_config_path()

        if json_mode:
            env = success_envelope(
                "pxcli config show",
                {
                    "config_path": str(config_path),
                    "save_cookies": config.save_cookies,
                    "debug_mode": config.debug_mode,
                    "env_overrides": _collect_env_overrides(),
                },
            )
            write_envelope(env, include_schema=_get_include_schema())
            return

        _output_config_text(config, config_path, _collect_env_overrides(prefix="  "))
        logger.debug("Configuration displayed successfully")

    except ConfigurationError as e:
        if json_mode:
            handle_error(e, command="pxcli config show", json_mode=True)
        click.echo(f"[ERROR] Failed to load configuration: {e}", err=True)
        logger.error(f"Configuration display failed: {e}", exc_info=True)
        sys.exit(1)
