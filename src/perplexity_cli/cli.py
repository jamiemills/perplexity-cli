"""Command-line interface for Perplexity CLI."""

from pathlib import Path

import click

from perplexity_cli import commands
from perplexity_cli.commands import register_commands
from perplexity_cli.utils.logging import get_default_log_file, setup_logging
from perplexity_cli.utils.version import get_version


@click.group()
@click.version_option(version=get_version())
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help=(
        "Enable verbose output at INFO level.  Logs informational messages "
        "to stderr (or to the log file if --log-file is specified).  Useful "
        "for understanding what the CLI is doing without full debug noise."
    ),
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    help=(
        "Enable debug output at DEBUG level.  Logs detailed diagnostic "
        "information including HTTP request/response details, timing data, "
        "and internal state.  Overrides --verbose.  Can also be enabled "
        "persistently via 'pxcli config set debug_mode true'."
    ),
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Write log output to a file instead of the default location.  "
        "Default: ~/.config/perplexity-cli/perplexity-cli.log.  The file is "
        "created if it does not exist.  Logs are appended, not overwritten."
    ),
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help=(
        "Suppress non-essential output such as progress messages and "
        "informational banners.  Errors and the primary command result are "
        "still printed.  Useful in scripts where only the answer matters."
    ),
)
@click.option(
    "--no-color",
    is_flag=True,
    help=(
        "Disable coloured output.  All ANSI escape codes are suppressed.  "
        "Automatically enabled when stdout is not a terminal or when the "
        "NO_COLOR environment variable is set.  Useful for piping output "
        "to files or other commands."
    ),
)
@click.pass_context
def main(
    ctx: click.Context,
    verbose: bool,
    debug: bool,
    log_file: Path | None,
    **_kwargs: object,
) -> None:
    """Perplexity CLI - Query Perplexity.ai from the command line.

    A command-line interface for querying Perplexity.ai, managing
    authentication, exporting conversation threads, and integrating with
    agent toolchains.  Supports structured JSON output (envelopes), NDJSON
    streaming, file attachments, and shell completion.

    All commands that produce structured output accept --json for a JSON
    envelope and --schema to embed the full JSON Schema in the output.
    Use 'pxcli schema' to inspect the envelope schema directly.

    \b
    Command groups:
      auth        Manage authentication (login, logout, status)
      config      Read and write persistent feature toggles
      models      List available models for your subscription tier
      style       Set, view, or clear a style prompt for all queries
      threads     Export conversation thread library
      skill       View the agent skill definition (SKILL.md)
      doctor      Run diagnostic checks on local storage and credentials
      completion  Generate shell completion scripts (bash, zsh, fish)

    \b
    Root commands:
      query       Submit a query and get an answer with references
      schema      Output the JSON Schema for all command envelopes

    \b
    Quick start:
      pxcli query "What is Python?"
      pxcli query --json "What is Python?" | jq -r '.result.answer'
      pxcli auth login
      pxcli auth status --verify
      pxcli config show

    Run any command with --help for full details, examples, example output,
    JSON envelope schemas, and option descriptions.
    """
    # Setup logging - check config for debug mode if no CLI flag
    if log_file is None:
        log_file = get_default_log_file()

    # Apply config debug mode if --debug flag not specified
    effective_debug = debug
    if not debug:
        from perplexity_cli.utils.config import get_debug_mode_enabled

        effective_debug = get_debug_mode_enabled()

    setup_logging(verbose=verbose, debug=effective_debug, log_file=log_file)

    # Store context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug


register_commands(main)

# Module-level exports for backward compatibility within the codebase
auth_group = commands.auth_group
auth_login = commands.auth_login
auth_logout = commands.auth_logout
auth_status = commands.auth_status
query = commands.query
config_group = commands.config_group
config_set = commands.config_set
config_show = commands.config_show
style_group = commands.style_group
style_set = commands.style_set
style_show = commands.style_show
style_clear = commands.style_clear
threads_group = commands.threads_group
threads_export = commands.threads_export
skill_group = commands.skill_group
skill_show = commands.skill_show
doctor = commands.doctor
doctor_security = commands.doctor_security
models_group = commands.models_group
models_list = commands.models_list


if __name__ == "__main__":
    main()
