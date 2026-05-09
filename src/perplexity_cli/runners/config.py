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
    except ValueError as e:
        if json_mode:
            handle_error(e, command="pxcli style set", json_mode=True)
        click.echo(f"[ERROR] Invalid style: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        if json_mode:
            handle_error(e, command="pxcli style set", json_mode=True)
        click.echo(f"[ERROR] Failed to save style: {e}", err=True)
        sys.exit(1)


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
        if json_mode:
            handle_error(e, command="pxcli style show", json_mode=True)
        click.echo(f"[ERROR] Error reading style: {e}", err=True)
        sys.exit(1)


def run_clear_style_command(*, json_mode: bool | None = None) -> None:
    """Execute the clear-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if json_mode is None:
        json_mode = _get_json_mode_from_ctx()

    sm = StyleManager()

    try:
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

    except OSError as e:
        if json_mode:
            handle_error(e, command="pxcli style clear", json_mode=True)
        click.echo(f"[ERROR] Error clearing style: {e}", err=True)
        sys.exit(1)


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
        if json_mode:
            handle_error(e, command="pxcli config set", json_mode=True)
        click.echo(f"[ERROR] Failed to update configuration: {e}", err=True)
        logger.error(f"Configuration update failed: {e}", exc_info=True)
        sys.exit(1)


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
            env_overrides = []
            if "PERPLEXITY_SAVE_COOKIES" in os.environ:
                env_overrides.append(
                    f"PERPLEXITY_SAVE_COOKIES={os.environ['PERPLEXITY_SAVE_COOKIES']}"
                )
            if "PERPLEXITY_DEBUG_MODE" in os.environ:
                env_overrides.append(f"PERPLEXITY_DEBUG_MODE={os.environ['PERPLEXITY_DEBUG_MODE']}")

            env = success_envelope(
                "pxcli config show",
                {
                    "config_path": str(config_path),
                    "save_cookies": config.save_cookies,
                    "debug_mode": config.debug_mode,
                    "env_overrides": env_overrides,
                },
            )
            write_envelope(env, include_schema=_get_include_schema())
            return

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
        if json_mode:
            handle_error(e, command="pxcli config show", json_mode=True)
        click.echo(f"[ERROR] Failed to load configuration: {e}", err=True)
        logger.error(f"Configuration display failed: {e}", exc_info=True)
        sys.exit(1)
