"""Configuration and style command runners."""

import os
import sys

import click

from perplexity_cli.utils.exceptions import ConfigurationError
from perplexity_cli.utils.logging import get_logger


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
