"""Command-line interface for Perplexity CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from perplexity_cli import attachments as _attachments_module
from perplexity_cli import commands, query_runner
from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.auth.utils import load_token_optional
from perplexity_cli.commands import register_commands
from perplexity_cli.error_handler import handle_error
from perplexity_cli.formatting import get_formatter, list_formatters
from perplexity_cli.utils.async_bridge import run_async
from perplexity_cli.utils.config import (
    get_config_paths,
    get_debug_mode_enabled,
    get_save_cookies_enabled,
)
from perplexity_cli.utils.file_handler import load_attachments, resolve_file_arguments
from perplexity_cli.utils.logging import (
    get_default_log_file,
    get_logger,
    redact_path,
    redact_text,
    redact_url,
    setup_logging,
)
from perplexity_cli.utils.style_manager import StyleManager
from perplexity_cli.utils.version import get_version

# ---------------------------------------------------------------------------
# Composition-root wiring: query_runner lives in the application layer and may
# not statically import adapter or presentation modules, so its seam
# attributes are populated here where every layer is importable.  Seams that
# are already bound (for example fakes installed by callers before cli is
# imported) are left untouched so the wiring is non-destructive.
# ---------------------------------------------------------------------------


def _wire_query_runner_seam(name: str, collaborator: Any) -> None:
    """Populate an unbound query_runner seam with a concrete collaborator."""
    if getattr(query_runner, name) is None:
        setattr(query_runner, name, collaborator)


def _attachment_uploader_factory(**kwargs: Any) -> Any:
    """Build the real attachment uploader, reading the seam at call time.

    The ``perplexity_cli.attachments.AttachmentUploader`` module attribute is
    patched by tests, so it must be re-read whenever an uploader is
    constructed rather than captured at import time.
    """
    return _attachments_module.AttachmentUploader(**kwargs)


_wire_query_runner_seam("handle_error", handle_error)
_wire_query_runner_seam("get_logger", get_logger)
_wire_query_runner_seam("redact_path", redact_path)
_wire_query_runner_seam("redact_text", redact_text)
_wire_query_runner_seam("redact_url", redact_url)
_wire_query_runner_seam("get_config_paths", get_config_paths)
_wire_query_runner_seam("get_save_cookies_enabled", get_save_cookies_enabled)
_wire_query_runner_seam("get_formatter", get_formatter)
_wire_query_runner_seam("list_formatters", list_formatters)
_wire_query_runner_seam("StyleManager", StyleManager)
_wire_query_runner_seam("TokenManager", TokenManager)
_wire_query_runner_seam("load_token_optional", load_token_optional)
_wire_query_runner_seam("PerplexityAPI", PerplexityAPI)
_wire_query_runner_seam("resolve_file_arguments", resolve_file_arguments)
_wire_query_runner_seam("load_attachments", load_attachments)
_wire_query_runner_seam("run_async", run_async)
_wire_query_runner_seam("AttachmentUploader", _attachment_uploader_factory)

# Typed container binding (F-002 remediation): the composition root installs
# every collaborator through one frozen object; legacy per-name seams remain
# during migration and are removed once no reader remains.
from perplexity_cli.query_deps import QueryDeps, bind_query_deps  # noqa: E402

bind_query_deps(
    QueryDeps(
        handle_error=handle_error,
        get_logger=get_logger,
        redact_path=redact_path,
        redact_text=redact_text,
        redact_url=redact_url,
        get_config_paths=get_config_paths,
        get_save_cookies_enabled=get_save_cookies_enabled,
        get_formatter=get_formatter,
        list_formatters=list_formatters,
        StyleManager=StyleManager,
        TokenManager=TokenManager,
        load_token_optional=load_token_optional,
        PerplexityAPI=PerplexityAPI,
        resolve_file_arguments=resolve_file_arguments,
        load_attachments=load_attachments,
        run_async=run_async,
        AttachmentUploader=_attachment_uploader_factory,
    )
)


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
        effective_debug = get_debug_mode_enabled()

    if effective_debug:
        verbosity = "debug"
    elif verbose:
        verbosity = "info"
    else:
        verbosity = "warning"
    setup_logging(verbosity=verbosity, log_file=log_file)

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
