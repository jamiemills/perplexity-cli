"""Configuration and style command runners."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Protocol, TypeGuard

import click

from perplexity_cli._types import OutputFormat, SchemaInclusion
from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error
from perplexity_cli.utils.exceptions import ConfigurationError
from perplexity_cli.utils.logging import get_logger

if TYPE_CHECKING:
    from perplexity_cli.utils.style_manager import StyleManager


def _is_str_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Guard: value is a dictionary with string keys and arbitrary values."""
    return isinstance(value, dict)


class _HasFeatureToggles(Protocol):
    """Protocol for objects that expose feature-config boolean fields."""

    save_cookies: bool
    debug_mode: bool


def _get_ctx_obj_dict() -> object:
    """Return the Click context object, or an empty dict if absent."""
    ctx = click.get_current_context(silent=True)
    if ctx is None:
        return {}
    obj: object = ctx.obj
    return obj if obj is not None else {}


def _read_ctx_bool(raw: object, attr: str) -> bool:
    """Read a boolean flag from the context object via dict get or getattr."""
    if _is_str_dict(raw):
        val: object = raw.get(attr, False)
        return bool(val)
    return bool(getattr(raw, attr, False))


def _get_include_schema() -> SchemaInclusion:
    """Read include_schema flag from Click context."""
    return "with_schema" if _read_ctx_bool(_get_ctx_obj_dict(), "schema") else "no_schema"


def _get_json_mode_from_ctx() -> OutputFormat:
    """Read json_mode flag from Click context."""
    return "json" if _read_ctx_bool(_get_ctx_obj_dict(), "json") else "human"


def _handle_style_error(
    e: Exception, output_format: OutputFormat, command: str, message: str
) -> None:
    """Handle style command errors uniformly."""
    if output_format == "json":
        handle_error(e, command, output_format="json")
    click.echo(f"[ERROR] {message}: {e}", err=True)
    sys.exit(1)


def run_configure_command(style: str, *, output_format: OutputFormat | None = None) -> None:
    """Execute the configure command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    sm: StyleManager = StyleManager()

    try:
        sm.save_style(style)
        if output_format == "json":
            env = success_envelope("pxcli style set", {"style": style})
            write_envelope(env, include_schema=_get_include_schema())
            return
        click.echo("[OK] Style configured successfully.")
        click.echo("[OK] Style will be applied to all future queries.")
        click.echo("\nStyle preview:")
        click.echo(f"  {style}")
    except (ValueError, OSError) as e:
        msg = "Invalid style" if isinstance(e, ValueError) else "Failed to save style"
        _handle_style_error(e, output_format, "pxcli style set", msg)


def _output_view_style(style: object) -> None:
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


def run_view_style_command(*, output_format: OutputFormat | None = None) -> None:
    """Execute the view-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    sm: StyleManager = StyleManager()

    try:
        style = sm.load_style()
        if output_format == "json":
            env = success_envelope("pxcli style show", {"style": style})
            write_envelope(env, include_schema=_get_include_schema())
            return
        _output_view_style(style)
    except OSError as e:
        _handle_style_error(e, output_format, "pxcli style show", "Error reading style")


def _execute_clear_style(sm: StyleManager, output_format: OutputFormat) -> None:
    """Perform the clear style operation and output results."""
    style = sm.load_style()
    had_style = style is not None

    if had_style:
        sm.clear_style()

    if output_format == "json":
        env = success_envelope("pxcli style clear", {"had_style": had_style})
        write_envelope(env, include_schema=_get_include_schema())
        return

    if not had_style:
        click.echo("No style is currently configured.")
        return

    click.echo("[OK] Style cleared successfully.")
    click.echo("[OK] Queries will no longer include a style prompt.")


def run_clear_style_command(*, output_format: OutputFormat | None = None) -> None:
    """Execute the clear-style command."""
    from perplexity_cli.utils.style_manager import StyleManager

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    sm: StyleManager = StyleManager()

    try:
        _execute_clear_style(sm, output_format)
    except OSError as e:
        _handle_style_error(e, output_format, "pxcli style clear", "Error clearing style")


_CONFIG_CHANGE_MESSAGES: dict[tuple[str, str], tuple[str, str]] = {
    ("save_cookies", "enabled"): (
        "[INFO] Cookie storage enabled.",
        "  Re-authenticate to save cookies: pxcli auth login",
    ),
    ("save_cookies", "disabled"): (
        "[INFO] Cookie storage disabled.",
        "  Only JWT token will be saved on next authentication.",
    ),
    ("debug_mode", "enabled"): (
        "[INFO] Debug mode enabled.",
        "  All commands will now log at DEBUG level.",
    ),
    ("debug_mode", "disabled"): (
        "[INFO] Debug mode disabled.",
        "  Use --debug flag for one-time debug output.",
    ),
}


def _print_config_change_message(key: str, bool_value: bool) -> None:
    """Print contextual message after a configuration change."""
    state = "enabled" if bool_value else "disabled"
    msgs = _CONFIG_CHANGE_MESSAGES.get((key, state))
    if msgs:
        click.echo(f"\n{msgs[0]}")
        click.echo(msgs[1])


def run_set_config_command(
    key: str, value: str, *, output_format: OutputFormat | None = None
) -> None:
    """Execute the set-config command."""
    from perplexity_cli.utils.config import clear_feature_config_cache, set_feature

    logger = get_logger()

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    try:
        bool_value = value.lower() == "true"
        set_feature(key, bool_value)
        clear_feature_config_cache()

        if output_format == "json":
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
        if output_format == "json":
            handle_error(e, "pxcli config set", output_format="json")
        click.echo(f"[ERROR] Failed to update configuration: {e}", err=True)
        logger.error("Configuration update failed: %s", e, exc_info=True)
        sys.exit(1)


_ENV_OVERRIDE_KEYS = ("PERPLEXITY_SAVE_COOKIES", "PERPLEXITY_DEBUG_MODE")


def _collect_env_overrides(prefix: str = "") -> list[str]:
    """Collect active environment variable overrides."""
    return [f"{prefix}{key}={os.environ[key]}" for key in _ENV_OVERRIDE_KEYS if key in os.environ]


def _output_config_text(
    config: _HasFeatureToggles, config_path: object, env_overrides: list[str]
) -> None:
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
    click.echo("  pxcli config set save_cookies true|false")
    click.echo("  pxcli config set debug_mode true|false")


def run_show_config_command(*, output_format: OutputFormat | None = None) -> None:
    """Execute the show-config command."""
    from perplexity_cli.utils.config import (
        FeatureConfig,
        get_feature_config,
        get_feature_config_path,
    )

    logger = get_logger()

    if output_format is None:
        output_format = _get_json_mode_from_ctx()

    try:
        config: FeatureConfig = get_feature_config()
        config_path = get_feature_config_path()

        if output_format == "json":
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
        if output_format == "json":
            handle_error(e, "pxcli config show", output_format="json")
        click.echo(f"[ERROR] Failed to load configuration: {e}", err=True)
        logger.error(f"Configuration display failed: {e}", exc_info=True)
        sys.exit(1)
