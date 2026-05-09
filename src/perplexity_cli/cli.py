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
    help="Enable verbose output (INFO level logging).",
)
@click.option(
    "--debug",
    "-d",
    is_flag=True,
    help="Enable debug output (DEBUG level logging).",
)
@click.option(
    "--log-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Write logs to file (default: ~/.config/perplexity-cli/perplexity-cli.log).",
)
@click.pass_context
def main(ctx: click.Context, verbose: bool, debug: bool, log_file: Path | None) -> None:
    """Perplexity CLI - Query Perplexity.ai from the command line.

    \b
    Command options:
      query           -f {plain,markdown,rich,json}  --strip-references
                      --stream / --no-stream
      auth            --port PORT
      export-threads  --from-date DATE  --to-date DATE  --output PATH
                      --force-refresh  --clear-cache
      configure       STYLE
      set-config      KEY VALUE

    Run any command with --help for full details, e.g. pxcli query --help
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

auth = commands.auth
query = commands.query
logout = commands.logout
configure = commands.configure
view_style = commands.view_style
clear_style = commands.clear_style
status = commands.status
set_config = commands.set_config
show_config = commands.show_config
doctor = commands.doctor
doctor_security = commands.doctor_security
show_skill = commands.show_skill
export_threads = commands.export_threads


if __name__ == "__main__":
    main()
