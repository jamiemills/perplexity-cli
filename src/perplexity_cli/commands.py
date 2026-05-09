"""Click command definitions for the CLI."""

from pathlib import Path

import click


@click.command()
@click.option(
    "--port",
    default=9222,
    help="Chrome remote debugging port (default: 9222)",
)
@click.pass_context
def auth(ctx: click.Context, port: int) -> None:
    """Authenticate with Perplexity.ai via Chrome DevTools Protocol.

    One-time setup to extract and store your authentication token securely.

    SETUP INSTRUCTIONS:

    1. Install Chrome for Testing:
        npx @puppeteer/browsers install chrome@stable

    2. Create a shell alias in ~/.bashrc, ~/.zshrc, etc.:
        alias chromefortesting='open ~/.local/bin/chrome/mac_arm-*/chrome-mac-arm64/Google\\ Chrome\\ for\\ Testing.app --args "--remote-debugging-port=9222" "about:blank"'

    3. Run authentication:
        chromefortesting           # Terminal 1: Start Chrome
        perplexity-cli auth        # Terminal 2: Extract token

    The token is then stored encrypted at ~/.config/perplexity-cli/token.json

    CUSTOM PORT:

    If port 9222 is in use, use --port to specify an alternative:
        perplexity-cli auth --port 9223

    Examples:
        perplexity-cli auth
        perplexity-cli auth --port 9223
    """
    from perplexity_cli.runners import run_auth_command

    run_auth_command(ctx.obj, port)


@click.command()
@click.argument("query_text", metavar="QUERY")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["plain", "markdown", "rich", "json"]),
    default=None,
    help="Output format: plain (text), markdown (GitHub-flavoured), rich (terminal with colours), or json (structured JSON). Defaults to 'rich'.",
)
@click.option(
    "--strip-references",
    is_flag=True,
    help="Remove all references section and inline citation numbers [1], [2], etc. from the answer.",
)
@click.option(
    "--stream/--no-stream",
    default=False,
    help="Stream response in real-time. Use --stream for incremental output (experimental).",
)
@click.option(
    "--attach",
    "-a",
    "attachments_str",
    multiple=True,
    help="File(s) to attach: comma-separated paths or repeated use. Supports directories (recursive). Examples: --attach file.txt or --attach 'file1.txt,file2.txt' or --attach ./docs",
)
@click.pass_context
def query(
    ctx: click.Context,
    query_text: str,
    output_format: str,
    strip_references: bool,
    stream: bool,
    attachments_str: tuple[str, ...],
) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    Works with or without authentication. Authentication is only required when using
    file attachments. The answer is printed to stdout, making it easy to pipe to
    other commands. By default, responses are displayed after the complete response
    is fetched (batch mode). Use --stream for real-time streaming.

    Output formats:
        plain    - Plain text with underlined headers (good for scripts)
        markdown - GitHub-flavoured Markdown with proper structure
        rich     - Colourful terminal output with tables (default)
        json     - Structured JSON with answer and references

    Use --strip-references to remove all citations [1], [2], etc. and the
    references section from the output.

    Use --stream for real-time streaming of the response as it arrives.

    Use --attach to include files with your query. Supports multiple methods:
        --attach file.txt           - Single file
        --attach file1.txt,file2.txt - Comma-separated files
        --attach ./directory        - All files in directory (recursive)
        --attach -a file1.txt -a file2.txt - Repeated flags

    Examples:
        perplexity-cli query "What is Python?"
        perplexity-cli query "What is the capital of France?" > answer.txt
        perplexity-cli query --format plain "What is Python?"
        perplexity-cli query --format markdown "What is Python?" > answer.md
        perplexity-cli query --format json "What is Python?" | jq -r '.answer'
        perplexity-cli query --format json "What is Python?" > answer.json
        perplexity-cli query --strip-references "What is Python?"
        perplexity-cli query -f plain --strip-references "What is Python?"
        perplexity-cli query --stream "What is Python?"
        perplexity-cli query --attach README.md "What is this project?"
        perplexity-cli query --attach config.json,data.txt "Analyse these files"
        perplexity-cli query --attach ./docs "Summarise all documentation"

    JSON format tip: Use jq -r to display newlines properly:
        perplexity-cli query --format json "Question" | jq -r '.answer'
    """
    from perplexity_cli.query_runner import run_query_command

    run_query_command(
        ctx.obj,
        query_text,
        output_format,
        strip_references,
        stream,
        attachments_str,
    )


@click.command()
def logout() -> None:
    """Log out and remove stored credentials.

    This deletes the stored authentication token. You will need to
    re-authenticate with 'perplexity-cli auth' before making queries.

    Example:
        perplexity-cli logout
    """
    from perplexity_cli.runners import run_logout_command

    run_logout_command()


@click.command()
@click.argument("style", required=True)
def configure(style: str) -> None:
    """Configure a style prompt to apply to all queries.

    Sets a custom style/prompt that will be automatically appended to all
    subsequent queries. This allows you to standardise response formatting
    without repeating instructions.

    The style is stored in ~/.config/perplexity-cli/style.json and persists
    across CLI sessions.

    Example:
        perplexity-cli configure "be brief and concise"
        perplexity-cli configure "provide super brief answers in minimal words"
    """
    from perplexity_cli.runners import run_configure_command

    run_configure_command(style)


@click.command()
def view_style() -> None:
    """View currently configured style.

    Displays the style prompt that is being applied to queries, or a message
    if no style is configured.

    Example:
        perplexity-cli view-style
    """
    from perplexity_cli.runners import run_view_style_command

    run_view_style_command()


@click.command()
def clear_style() -> None:
    """Clear configured style.

    Removes the style configuration. Queries will no longer have any style
    prompt appended.

    Example:
        perplexity-cli clear-style
    """
    from perplexity_cli.runners import run_clear_style_command

    run_clear_style_command()


@click.command()
@click.option(
    "--verify",
    is_flag=True,
    default=False,
    help="Perform a live API verification check.",
)
def status(verify: bool) -> None:
    """Show current authentication status.

    Displays whether you are authenticated and where the token is stored.
    Use --verify to perform a live API verification check.

    Example:
        perplexity-cli status
        perplexity-cli status --verify
    """
    from perplexity_cli.runners import run_status_command

    run_status_command(verify)


@click.command(name="set-config")
@click.argument("key", type=click.Choice(["save_cookies", "debug_mode"]))
@click.argument("value", type=click.Choice(["true", "false"]))
@click.pass_context
def set_config(ctx: click.Context, key: str, value: str) -> None:
    """Set configuration options.

    Configure feature toggles for pxcli.

    Arguments:
        KEY: Configuration key (save_cookies or debug_mode)
        VALUE: Configuration value (true or false)

    Examples:
        pxcli set-config save_cookies true
        pxcli set-config debug_mode false
    """
    from perplexity_cli.runners import run_set_config_command

    run_set_config_command(key, value)


@click.command(name="show-config")
@click.pass_context
def show_config(ctx: click.Context) -> None:
    """Display current configuration.

    Shows feature toggle settings and their sources.

    Example:
        pxcli show-config
    """
    from perplexity_cli.runners import run_show_config_command

    run_show_config_command()


@click.group()
def doctor() -> None:
    """Diagnostic commands for local environment and storage state."""


@click.command(name="security")
def doctor_security() -> None:
    """Report local credential and cache storage security details.

    Shows the current storage backend, file locations, cookie-storage setting,
    and whether token/cache file permissions are restricted correctly.
    """
    from perplexity_cli.runners import run_doctor_security_command

    run_doctor_security_command()


doctor.add_command(doctor_security)


@click.command()
def show_skill() -> None:
    """Display the Agent Skill definition for using perplexity-cli.

    Shows the SKILL.md content that describes how to use perplexity-cli
    as an alternative to web search, including JSON output parsing examples
    and practical patterns for integration.

    Example:
        perplexity-cli show-skill
    """
    from perplexity_cli.runners import run_show_skill_command

    run_show_skill_command()


@click.command()
@click.option(
    "--from-date",
    type=str,
    default=None,
    help="Start date for filtering (ISO 8601 format: YYYY-MM-DD)",
)
@click.option(
    "--to-date",
    type=str,
    default=None,
    help="End date for filtering (ISO 8601 format: YYYY-MM-DD)",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Output CSV file path (default: threads-TIMESTAMP.csv)",
)
@click.option(
    "--force-refresh",
    is_flag=True,
    default=False,
    help="Ignore local cache and fetch fresh data from API",
)
@click.option(
    "--clear-cache",
    is_flag=True,
    default=False,
    help="Delete local cache file before export",
)
@click.pass_context
def export_threads(
    ctx: click.Context,
    from_date: str | None,
    to_date: str | None,
    output: Path | None,
    force_refresh: bool,
    clear_cache: bool,
) -> None:
    """Export thread library with titles and creation dates as CSV.

    Extracts all threads from your Perplexity.ai library using your stored
    authentication token. No browser required after initial auth setup.

    Includes:
    - Thread title
    - Creation date and time (ISO 8601 with timezone)
    - Thread URL
    - Reuse of saved browser cookies when available

    Uses local encrypted cache to avoid repeated API calls. Cache is automatically
    updated with newly fetched threads and used on subsequent exports.

    Optional date filtering to export specific date ranges.

    Examples:
        perplexity-cli export-threads
        perplexity-cli export-threads --from-date 2025-01-01
        perplexity-cli export-threads --from-date 2025-01-01 --to-date 2025-12-31
        perplexity-cli export-threads --output my-threads.csv
        perplexity-cli export-threads --force-refresh
        perplexity-cli export-threads --clear-cache

    The command uses your stored authentication token from the initial
    'perplexity-cli auth' setup. If you haven't authenticated yet, run:
        perplexity-cli auth
    """
    from perplexity_cli.runners import run_export_threads_command

    run_export_threads_command(
        ctx.obj,
        from_date,
        to_date,
        output,
        force_refresh,
        clear_cache,
    )


def register_commands(main: click.Group) -> None:
    """Attach all command definitions to the root Click group."""

    for command in (
        auth,
        query,
        logout,
        configure,
        view_style,
        clear_style,
        status,
        set_config,
        show_config,
        doctor,
        show_skill,
        export_threads,
    ):
        main.add_command(command)
