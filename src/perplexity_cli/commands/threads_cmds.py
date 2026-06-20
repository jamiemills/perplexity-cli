"""``pxcli threads`` group: export subcommand."""

from __future__ import annotations

from pathlib import Path

import click

from perplexity_cli.commands._ctx import (
    ClickValue,
    _ensure_ctx_obj,
    as_bool,
    as_path_or_none,
    as_str_or_none,
    record_output_flags,
)
from perplexity_cli.commands._examples import THREADS_EXPORT_JSON_EXAMPLE
from perplexity_cli.commands._help_refs import AUTH_LOGIN_HELP_REF
from perplexity_cli.commands._help_sections import HelpSectionConfig, add_help_sections
from perplexity_cli.commands._runner_adapter import (
    ExportRequest,
    run_export_threads_command,
)


@click.group(
    "threads",
    help=(
        "Thread management commands.\n\n"
        "Manage your Perplexity.ai conversation threads.  Currently supports "
        "exporting your full thread library (titles, dates, URLs) to CSV or JSON "
        "format.\n\n"
        "Requires authentication — run 'pxcli auth login' first.\n\n"
        "Subcommands:\n\n"
        "  export  - Export thread library as CSV or JSON\n\n"
        "Quick start:\n\n"
        "  pxcli threads export\n\n"
        "  pxcli threads export --from-date 2025-01-01\n\n"
        "  pxcli threads export --json"
    ),
)
@click.pass_context
def threads_group(ctx: click.Context) -> None:
    """Thread management commands."""
    _ensure_ctx_obj(ctx)


@click.command(name="export")
@click.option(
    "--from-date",
    type=str,
    default=None,
    help=(
        "Start date for filtering exported threads (inclusive).  Only threads "
        "created on or after this date are included.  Format: ISO 8601 date "
        "(YYYY-MM-DD).  Example: --from-date 2025-01-01.  If omitted, no lower "
        "bound is applied."
    ),
)
@click.option(
    "--to-date",
    type=str,
    default=None,
    help=(
        "End date for filtering exported threads (inclusive).  Only threads "
        "created on or before this date are included.  Format: ISO 8601 date "
        "(YYYY-MM-DD).  Example: --to-date 2025-12-31.  If omitted, no upper "
        "bound is applied."
    ),
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Output CSV file path.  If omitted, defaults to "
        "threads-YYYYMMDD-HHMMSS.csv in the current directory.  The file is "
        "created with UTF-8 encoding and includes a header row.  "
        "Example: --output my-threads.csv"
    ),
)
@click.option(
    "--force-refresh",
    is_flag=True,
    default=False,
    help=(
        "Ignore the local thread cache and fetch fresh data from the "
        "Perplexity.ai API.  The cache is updated with the newly fetched data "
        "after a successful export.  Use this when you know there are new "
        "threads that are not yet reflected in the cache."
    ),
)
@click.option(
    "--clear-cache",
    is_flag=True,
    default=False,
    help=(
        "Delete the local thread cache file before performing the export.  "
        "This forces a full re-fetch from the API.  The cache file is located "
        "at ~/.config/perplexity-cli/threads_cache.json.  Use this to recover "
        "from a corrupted cache."
    ),
)
@click.option(
    "--json",
    "json_flag",
    is_flag=True,
    help=(
        "Emit output as a structured JSON envelope to stdout instead of "
        "writing a CSV file.  The envelope contains the full thread list in "
        "the result.threads array.  Intended for programmatic consumption."
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
def threads_export(ctx: click.Context, **params: ClickValue) -> None:
    """Export thread library with titles and creation dates.

    Extracts all conversation threads from your Perplexity.ai library using
    your stored authentication token.  No browser is required after the
    initial 'pxcli auth login' setup.

    By default, output is written as a CSV file with columns: title,
    created_at (ISO 8601 with timezone), and url.  Use --json for structured
    JSON output instead.

    \b
    Features:
      - Exports thread title, creation timestamp, and URL
      - Local encrypted cache avoids redundant API calls
      - Cache is incrementally updated on each export
      - Date filtering via --from-date and --to-date
      - Reuses saved browser cookies when available

    \b
    Result fields (--json):
      threads      - Array of thread objects {title, created_at, url}
      total        - Total number of exported threads (integer)
      output_path  - Path to the CSV file written (or "stdout" for --json)
      date_range   - Applied date filter {from, to} (null values if unfiltered)

    \b
    Examples:
        pxcli threads export
        pxcli threads export --from-date 2025-01-01
        pxcli threads export --from-date 2025-01-01 --to-date 2025-06-30
        pxcli threads export --output my-threads.csv
        pxcli threads export -o my-threads.csv
        pxcli threads export --force-refresh
        pxcli threads export --clear-cache
        pxcli threads export --json
        pxcli threads export --json | jq '.result.threads[] | .title'
        pxcli threads export --json --from-date 2025-01-01 | jq '.result.total'

    \b
    Example Output (human):
        Fetching threads...
        Exported 47 threads to threads-20250509-143022.csv

    \b
    CSV format:
        title,created_at,url
        "How does quantum computing work?",2025-05-08T14:30:00+00:00,https://...
        "Best Python testing frameworks",2025-05-07T09:15:00+00:00,https://...
    """
    record_output_flags(ctx, params)
    request = ExportRequest(
        from_date=as_str_or_none(params.get("from_date")),
        to_date=as_str_or_none(params.get("to_date")),
        output=as_path_or_none(params.get("output")),
        force_refresh=as_bool(params.get("force_refresh")),
        clear_cache=as_bool(params.get("clear_cache")),
    )
    run_export_threads_command(ctx.obj, request)


threads_group.add_command(threads_export)


add_help_sections(
    threads_export,
    HelpSectionConfig(
        json_example=THREADS_EXPORT_JSON_EXAMPLE,
        json_schema=True,
        exit_codes=True,
        see_also=(AUTH_LOGIN_HELP_REF,),
        env_vars=("PERPLEXITY_CONFIG_DIR", "XDG_CONFIG_HOME"),
    ),
)
