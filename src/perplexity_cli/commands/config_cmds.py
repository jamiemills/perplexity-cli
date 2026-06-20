"""``pxcli config`` group: set, show subcommands."""

from __future__ import annotations

import click

from perplexity_cli.commands._ctx import ClickValue, _ensure_ctx_obj, record_output_flags
from perplexity_cli.commands._examples import (
    CONFIG_SET_JSON_EXAMPLE,
    CONFIG_SHOW_JSON_EXAMPLE,
)
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections


@click.group(
    "config",
    help=(
        "Configuration commands.\n\n"
        "Read and write persistent feature toggles that control CLI behaviour.  "
        "Configuration is stored in a JSON file at the path determined by "
        "(in order of precedence): PERPLEXITY_CONFIG_DIR, XDG_CONFIG_HOME, "
        "or ~/.config/perplexity-cli/config.json.\n\n"
        "Available configuration keys:\n\n"
        "  save_cookies  - When true, browser cookies captured during 'auth login'\n"
        "                  are stored alongside the token and reused for API\n"
        "                  requests.  Improves reliability of some operations.\n\n"
        "  debug_mode    - When true, enables DEBUG-level logging for all commands\n"
        "                  without needing the --debug flag.\n\n"
        "Subcommands:\n\n"
        "  set   - Write a configuration value\n\n"
        "  show  - Display all current configuration values and their sources\n\n"
        "Quick start:\n\n"
        "  pxcli config show                  # View current settings\n\n"
        "  pxcli config set save_cookies true  # Enable cookie storage\n\n"
        "  pxcli config set debug_mode false   # Disable debug logging"
    ),
)
@click.pass_context
def config_group(ctx: click.Context) -> None:
    """Configuration commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="set")
@click.argument("key", type=click.Choice(["save_cookies", "debug_mode"]))
@click.argument("value", type=click.Choice(["true", "false"]))
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  Intended for programmatic consumption."
    ),
)
@click.option(
    "--schema",
    "schema_flag",
    is_flag=True,
    help=(
        "Embed the full JSON Schema definition as a $schema key in the JSON "
        "envelope output.  Only effective when --json is also specified."
    ),
)
@click.pass_context
def config_set(ctx: click.Context, key: str, value: str, **flags: ClickValue) -> None:
    """Set a configuration option.

    Writes a boolean feature toggle to the persistent configuration file.
    The value takes effect immediately for all subsequent CLI invocations.

    \b
    Arguments:
      KEY    Configuration key to set.  Must be one of:
               save_cookies - Control whether browser cookies are stored
                              and reused for API requests.
               debug_mode   - Control whether DEBUG-level logging is enabled
                              by default (equivalent to --debug flag).
      VALUE  The boolean value to set.  Must be 'true' or 'false'.

    The configuration file is created automatically if it does not exist.
    The file path is determined by PERPLEXITY_CONFIG_DIR, XDG_CONFIG_HOME,
    or defaults to ~/.config/perplexity-cli/config.json.

    \b
    Examples:
        pxcli config set save_cookies true
        pxcli config set save_cookies false
        pxcli config set debug_mode true
        pxcli config set debug_mode false
        pxcli config set save_cookies true --json
        pxcli config set save_cookies true --json | jq '.result'

    \b
    Example Output (human):
        [OK] save_cookies set to true
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_set_config_command

    run_set_config_command(key, value)


@click.command(name="show")
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "human-readable text.  The envelope contains {ok, command, result, meta, "
        "next_actions} on success.  Intended for programmatic consumption."
    ),
)
@click.option(
    "--schema",
    "schema_flag",
    is_flag=True,
    help=(
        "Embed the full JSON Schema definition as a $schema key in the JSON "
        "envelope output.  Only effective when --json is also specified."
    ),
)
@click.pass_context
def config_show(ctx: click.Context, **flags: ClickValue) -> None:
    """Display current configuration.

    Reads the persistent configuration file and displays all feature toggle
    settings along with their current values.  Also reports the configuration
    file path and any environment variable overrides that are in effect.

    \b
    Result fields:
      config_path    - Absolute path to the configuration file
      save_cookies   - Whether browser cookie storage is enabled (boolean)
      debug_mode     - Whether debug logging is enabled by default (boolean)
      env_overrides  - List of config keys overridden by environment variables

    \b
    Examples:
        pxcli config show
        pxcli config show --json
        pxcli config show --json | jq '.result.save_cookies'

    \b
    Example Output (human):
        Configuration (/Users/you/.config/perplexity-cli/config.json):
          save_cookies: true
          debug_mode:   false
    """
    record_output_flags(ctx, flags)
    from perplexity_cli.runners import run_show_config_command

    run_show_config_command()


config_group.add_command(config_set)
config_group.add_command(config_show)


add_help_sections(
    config_set,
    HelpSectionConfig(
        json_example=CONFIG_SET_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=("pxcli config show",),
        env_vars=("PERPLEXITY_CONFIG_DIR", "XDG_CONFIG_HOME"),
    ),
)
add_help_sections(
    config_show,
    HelpSectionConfig(
        json_example=CONFIG_SHOW_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=("pxcli config set",),
        env_vars=("PERPLEXITY_CONFIG_DIR", "XDG_CONFIG_HOME"),
    ),
)
