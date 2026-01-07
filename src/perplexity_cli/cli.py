"""Command-line interface for Perplexity CLI."""

import sys
from importlib.resources import files
from pathlib import Path

import click
import httpx

from perplexity_cli.api.endpoints import PerplexityAPI
from perplexity_cli.auth.oauth_handler import authenticate_sync
from perplexity_cli.auth.token_manager import TokenManager
from perplexity_cli.formatting import get_formatter, list_formatters
from perplexity_cli.utils.config import get_perplexity_base_url
from perplexity_cli.utils.logging import get_default_log_file, setup_logging
from perplexity_cli.utils.style_manager import StyleManager
from perplexity_cli.utils.version import get_version

# Load Agent Skill definition for display via show-skill command
try:
    SKILL_CONTENT = (
        files("perplexity_cli.resources").joinpath("skill.md").read_text(encoding="utf-8")
    )
except (FileNotFoundError, AttributeError):
    # Fallback if skill.md is not found
    SKILL_CONTENT = (
        "Agent Skill definition not available. Run 'perplexity-cli --help' for usage information."
    )


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
    """Perplexity CLI - Query Perplexity.ai from the command line."""
    # Setup logging
    if log_file is None:
        log_file = get_default_log_file()
    setup_logging(verbose=verbose, debug=debug, log_file=log_file)

    # Store context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["debug"] = debug


@main.command()
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
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    logger.info(f"Starting authentication on port {port}")

    base_url = get_perplexity_base_url()
    click.echo("Authenticating with Perplexity.ai...")
    click.echo(f"\nMake sure Chrome is running with --remote-debugging-port={port}")
    click.echo(f"Navigate to {base_url} and log in if needed.\n")

    try:
        # Authenticate and extract token and cookies
        logger.debug("Calling authenticate_sync")
        token, cookies = authenticate_sync(port=port)
        logger.info(f"Token and {len(cookies)} cookies extracted successfully")

        # Save token and cookies
        tm = TokenManager()
        tm.save_token(token, cookies=cookies)
        logger.info(f"Token and cookies saved to {tm.token_path}")

        click.echo("✓ Authentication successful!")
        click.echo(f"✓ Token saved to: {tm.token_path}")
        click.echo(f"✓ {len(cookies)} cookies saved (including Cloudflare cookies)")
        click.echo('\nYou can now use: pxcli query "<your question>"')

    except RuntimeError as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        click.echo(f"✗ Authentication failed: {e}", err=True)
        click.echo("\nTroubleshooting:", err=True)
        click.echo(
            f"  1. Start Chrome with: --remote-debugging-port={port}",
            err=True,
        )
        click.echo(
            f"  2. Navigate to {base_url} in Chrome",
            err=True,
        )
        click.echo("  3. Log in with your Google account", err=True)
        click.echo("  4. Run this command again", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Authentication interrupted by user")
        click.echo("\n✗ Authentication interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error during authentication: {e}")
        click.echo(f"✗ Unexpected error: {e}", err=True)
        if ctx.obj.get("debug", False):
            import traceback

            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@main.command()
@click.argument("query_text", metavar="QUERY")
@click.option(
    "--format",
    "-f",
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
    "--stream",
    is_flag=True,
    help="Stream response in real-time as it arrives (experimental).",
)
@click.pass_context
def query(
    ctx: click.Context,
    query_text: str,
    format: str,
    strip_references: bool,
    stream: bool,
) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    The answer is printed to stdout, making it easy to pipe to other commands.

    Output formats:
        plain    - Plain text with underlined headers (good for scripts)
        markdown - GitHub-flavoured Markdown with proper structure
        rich     - Colourful terminal output with tables (default)
        json     - Structured JSON with answer and references

    Use --strip-references to remove all citations [1], [2], etc. and the
    references section from the output.

    Use --stream to see the response as it arrives in real-time.

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

    JSON format tip: Use jq -r to display newlines properly:
        perplexity-cli query --format json "Question" | jq -r '.answer'
    """
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    logger.debug(
        f"Query command invoked: query='{query_text[:50]}...', format={format}, stream={stream}"
    )

    # Load token and cookies
    tm = TokenManager()
    token, cookies = tm.load_token()

    if not token:
        click.echo("✗ Not authenticated.", err=True)
        click.echo(
            "\nPlease authenticate first with: pxcli auth",
            err=True,
        )
        logger.warning("Query attempted without authentication")
        sys.exit(1)

    try:
        # Determine output format
        output_format = format or "rich"

        # Get formatter instance
        try:
            formatter = get_formatter(output_format)
        except ValueError as e:
            click.echo(f"✗ {e}", err=True)
            available = ", ".join(list_formatters())
            click.echo(f"Available formats: {available}", err=True)
            logger.error(f"Invalid formatter: {format}")
            sys.exit(1)

        # Load style if configured
        sm = StyleManager()
        style = sm.load_style()

        # Append style to query if one is configured
        final_query = query_text
        if style:
            final_query = f"{query_text}\n\n{style}"
            logger.debug(f"Applied style: {style[:50]}...")

        # Create API client with cookies
        api = PerplexityAPI(token=token, cookies=cookies)

        # Handle streaming vs complete answer
        if stream:
            logger.info("Streaming query response")
            # Stream response
            _stream_query_response(api, final_query, formatter, output_format, strip_references)
        else:
            logger.info("Fetching complete answer")
            # Submit query and get answer
            answer_obj = api.get_complete_answer(final_query)
            logger.debug(
                f"Received answer: {len(answer_obj.text)} characters, {len(answer_obj.references)} references"
            )

            # Format and output the answer
            if output_format == "rich":
                # Use Rich formatter's direct rendering for proper styling
                formatter.render_complete(answer_obj, strip_references=strip_references)
            else:
                # For plain and markdown, use click.echo
                formatted_output = formatter.format_complete(
                    answer_obj, strip_references=strip_references
                )
                click.echo(formatted_output)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error(f"HTTP error {status}: {e}")
        if status == 401:
            click.echo("✗ Authentication failed. Token may be expired.", err=True)
            click.echo("\nRe-authenticate with: perplexity-cli auth", err=True)
        elif status == 403:
            click.echo("✗ Access forbidden. Check your permissions.", err=True)
        elif status == 429:
            click.echo("✗ Rate limit exceeded. Please wait and try again.", err=True)
        else:
            click.echo(f"✗ HTTP error {status}.", err=True)
            if ctx.obj.get("debug", False):
                click.echo(f"Details: {e}", err=True)
        sys.exit(1)

    except httpx.RequestError as e:
        logger.error(f"Network error: {e}")
        click.echo("✗ Network error. Please check your internet connection.", err=True)
        if ctx.obj.get("debug", False):
            click.echo(f"Details: {e}", err=True)
        sys.exit(1)

    except ValueError as e:
        logger.error(f"Value error: {e}")
        click.echo(f"✗ Error: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Query interrupted by user")
        click.echo("\n✗ Query interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        click.echo("✗ An unexpected error occurred.", err=True)
        if ctx.obj.get("debug", False):
            import traceback

            click.echo(f"Debug info:\n{traceback.format_exc()}", err=True)
        else:
            click.echo("Run with --debug for more information.", err=True)
        sys.exit(1)


def _stream_query_response(
    api: PerplexityAPI,
    query: str,
    formatter,
    output_format: str,
    strip_references: bool,
) -> None:
    """Stream query response in real-time.

    Args:
        api: PerplexityAPI instance.
        query: Query text.
        formatter: Formatter instance.
        output_format: Output format name.
        strip_references: Whether to strip references.
    """
    from perplexity_cli.api.models import Answer, WebResult
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    accumulated_text = ""
    references: list[WebResult] = []

    try:
        for message in api.submit_query(query):
            logger.debug(
                f"Received SSE message: status={message.status}, final={message.final_sse_message}"
            )

            # Extract text from blocks
            for block in message.blocks:
                if block.intended_usage == "ask_text":
                    text = api._extract_text_from_block(block.content)
                    if text and text != accumulated_text:
                        # Only print new text
                        new_text = text[len(accumulated_text) :]
                        if new_text:
                            if output_format == "rich":
                                # For rich, print incrementally
                                click.echo(new_text, nl=False)
                            else:
                                click.echo(new_text, nl=False)
                            accumulated_text = text

            # Extract references from final message
            if message.final_sse_message and message.web_results:
                references = message.web_results
                logger.debug(f"Extracted {len(references)} references")

        # Print newline after streaming
        click.echo()

        # Print references if not stripped
        if references and not strip_references:
            click.echo()
            if output_format == "rich":
                formatter.render_complete(
                    Answer(text=accumulated_text, references=references),
                    strip_references=True,  # Already printed text
                )
            else:
                formatted_refs = formatter.format_references(references)
                if formatted_refs:
                    click.echo(formatted_refs)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error(f"HTTP error {status} during streaming: {e}")
        click.echo()  # Newline after streamed content
        if status == 401:
            click.echo("✗ Authentication failed. Token may be expired.", err=True)
            click.echo("\nRe-authenticate with: perplexity-cli auth", err=True)
            sys.exit(1)
        elif status == 403:
            click.echo("✗ Access forbidden. Check your permissions.", err=True)
            sys.exit(1)
        elif status == 429:
            click.echo("✗ Rate limit exceeded. Please wait and try again.", err=True)
            sys.exit(1)
        else:
            click.echo(f"✗ HTTP error {status}.", err=True)
            sys.exit(1)

    except httpx.RequestError as e:
        logger.error(f"Network error during streaming: {e}")
        click.echo()  # Newline after streamed content
        click.echo("✗ Network error. Please check your internet connection.", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Streaming interrupted by user")
        click.echo("\n✗ Streaming interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error during streaming: {e}")
        click.echo()  # Newline after streamed content
        click.echo("✗ An unexpected error occurred.", err=True)
        click.echo("Run with --debug for more information.", err=True)
        sys.exit(1)


@main.command()
def logout() -> None:
    """Log out and remove stored credentials.

    This deletes the stored authentication token. You will need to
    re-authenticate with 'perplexity-cli auth' before making queries.

    Example:
        perplexity-cli logout
    """
    tm = TokenManager()

    if not tm.token_exists():
        click.echo("No stored credentials found.")
        return

    try:
        tm.clear_token()
        click.echo("✓ Logged out successfully.")
        click.echo("✓ Stored credentials removed.")

    except Exception as e:
        from perplexity_cli.utils.logging import get_logger

        logger = get_logger()
        logger.error(f"Error during logout: {e}", exc_info=True)
        click.echo(f"✗ Error during logout: {e}", err=True)
        sys.exit(1)


@main.command()
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
    sm = StyleManager()

    try:
        sm.save_style(style)
        click.echo("✓ Style configured successfully.")
        click.echo("✓ Style will be applied to all future queries.")
        click.echo("\nStyle preview:")
        click.echo(f"  {style}")
    except ValueError as e:
        click.echo(f"✗ Invalid style: {e}", err=True)
        sys.exit(1)
    except OSError as e:
        click.echo(f"✗ Failed to save style: {e}", err=True)
        sys.exit(1)


@main.command()
def view_style() -> None:
    """View currently configured style.

    Displays the style prompt that is being applied to queries, or a message
    if no style is configured.

    Example:
        perplexity-cli view-style
    """
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
        click.echo(f"✗ Error reading style: {e}", err=True)
        sys.exit(1)


@main.command()
def clear_style() -> None:
    """Clear configured style.

    Removes the style configuration. Queries will no longer have any style
    prompt appended.

    Example:
        perplexity-cli clear-style
    """
    sm = StyleManager()

    try:
        style = sm.load_style()

        if style is None:
            click.echo("No style is currently configured.")
            return

        sm.clear_style()
        click.echo("✓ Style cleared successfully.")
        click.echo("✓ Queries will no longer include a style prompt.")

    except OSError as e:
        click.echo(f"✗ Error clearing style: {e}", err=True)
        sys.exit(1)


@main.command()
def status() -> None:
    """Show current authentication status.

    Displays whether you are authenticated and where the token is stored.
    Attempts to verify token validity by making a test query.

    Example:
        perplexity-cli status
    """
    from datetime import datetime

    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    tm = TokenManager()

    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)

    if tm.token_exists():
        try:
            token, cookies = tm.load_token()
            if token:
                click.echo("Status: ✓ Authenticated")
                click.echo(f"Token file: {tm.token_path}")
                click.echo(f"Token length: {len(token)} characters")
                if cookies:
                    click.echo(f"Cookies: {len(cookies)} stored")

                # Show token file metadata
                try:
                    stat = tm.token_path.stat()
                    modified_time = datetime.fromtimestamp(stat.st_mtime)
                    click.echo(
                        f"Token last modified: {modified_time.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                except Exception:
                    pass

                # Try to verify token works with a minimal test query
                try:
                    logger.debug("Verifying token validity")
                    api = PerplexityAPI(token=token, cookies=cookies, timeout=10)
                    # Use a very short test query to verify token
                    test_answer = api.get_complete_answer("test")
                    if test_answer and len(test_answer.text) > 0:
                        click.echo("\n✓ Token is valid and working")
                        logger.info("Token verification successful")
                    else:
                        click.echo("\n⚠ Token verification returned empty response")
                        logger.warning("Token verification returned empty response")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401:
                        click.echo("\n✗ Token is invalid or expired")
                        logger.warning("Token verification failed: 401 Unauthorized")
                    else:
                        click.echo(f"\n⚠ Token verification failed (HTTP {e.response.status_code})")
                        logger.warning(f"Token verification failed: HTTP {e.response.status_code}")
                except Exception as e:
                    click.echo("\n⚠ Token verification failed (unable to test)")
                    logger.debug(f"Token verification error: {e}", exc_info=True)

            else:
                click.echo("Status: ✗ Not authenticated")
        except RuntimeError as e:
            click.echo("Status: ⚠ Token file has insecure permissions")
            click.echo(f"Error: {e}")
            click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
            logger.error(f"Token file has insecure permissions: {e}")
    else:
        click.echo("Status: ✗ Not authenticated")
        click.echo("\nAuthenticate with: perplexity-cli auth")


@main.command()
def show_skill() -> None:
    """Display the Agent Skill definition for using perplexity-cli.

    Shows the SKILL.md content that describes how to use perplexity-cli
    as an alternative to web search, including JSON output parsing examples
    and practical patterns for integration.

    Example:
        perplexity-cli show-skill
    """
    click.echo(SKILL_CONTENT)


@main.command()
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
    import asyncio

    from perplexity_cli.threads.exporter import write_threads_csv
    from perplexity_cli.threads.scraper import ThreadScraper
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    logger.info("Starting thread export")

    click.echo("Exporting threads from Perplexity.ai library...")

    # Load token and cookies
    tm = TokenManager()
    token, cookies = tm.load_token()

    if not token:
        click.echo("✗ Not authenticated.", err=True)
        click.echo(
            "\nPlease authenticate first with: pxcli auth",
            err=True,
        )
        logger.warning("Export attempted without authentication")
        sys.exit(1)

    # Load rate limiting configuration
    from perplexity_cli.utils.config import get_rate_limiting_config
    from perplexity_cli.utils.rate_limiter import RateLimiter

    rate_limit_config = get_rate_limiting_config()

    rate_limiter = None
    if rate_limit_config.get("enabled", True):
        rate_limiter = RateLimiter(
            requests_per_period=rate_limit_config["requests_per_period"],
            period_seconds=rate_limit_config["period_seconds"],
        )
        logger.info(
            f"Rate limiting enabled: {rate_limit_config['requests_per_period']} requests per "
            f"{rate_limit_config['period_seconds']} seconds"
        )

    # Initialise cache manager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager

    cache_manager = ThreadCacheManager()

    # Handle cache deletion if requested
    if clear_cache:
        if cache_manager.cache_exists():
            cache_manager.clear_cache()
            click.echo("✓ Cache cleared")
            logger.info("Cache cleared by user")
        else:
            click.echo("ℹ No cache file to clear")

    # Validate date range if provided
    if from_date or to_date:
        try:
            from dateutil import parser as dateutil_parser

            if from_date:
                dateutil_parser.parse(from_date)
            if to_date:
                dateutil_parser.parse(to_date)
        except ValueError as e:
            click.echo(f"✗ Invalid date format: {e}", err=True)
            click.echo("Please use YYYY-MM-DD format (e.g., 2025-12-23)", err=True)
            sys.exit(1)

    try:
        # Create scraper instance with token, rate limiter, and cache manager
        scraper = ThreadScraper(
            token=token,
            rate_limiter=rate_limiter,
            cache_manager=cache_manager,
            force_refresh=force_refresh,
        )

        # Progress tracking
        def update_progress(current: int, total: int) -> None:
            """Progress callback for scraping."""
            click.echo(f"\rExtracting {current} threads...", nl=False)

        # Run async scraping
        async def run_scrape() -> list:
            return await scraper.scrape_all_threads(
                from_date=from_date,
                to_date=to_date,
                progress_callback=update_progress,
            )

        threads = asyncio.run(run_scrape())

        # Clear the progress line
        click.echo()

        if not threads:
            click.echo("\n✗ No threads found matching criteria.", err=True)
            if from_date or to_date:
                click.echo(
                    f"Date range: {from_date or 'beginning'} to {to_date or 'end'}",
                    err=True,
                )
            sys.exit(1)

        # Write CSV
        output_path = write_threads_csv(threads, output)
        logger.info(f"Exported {len(threads)} threads to {output_path}")

        # Success message
        click.echo("\n✓ Export complete")
        click.echo(f"✓ Exported {len(threads)} threads")
        if from_date or to_date:
            click.echo(
                f"✓ Filtered by date range: {from_date or 'beginning'} to {to_date or 'end'}"
            )
        click.echo(f"✓ Saved to: {output_path.resolve()}")

    except RuntimeError as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        click.echo(f"\n✗ Export failed: {e}", err=True)
        if "Authentication failed" in str(e):
            click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
            click.echo("  perplexity-cli auth", err=True)
        sys.exit(1)

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        logger.error(f"HTTP error {status}: {e}")
        if status == 401:
            click.echo("✗ Authentication failed. Token may be expired.", err=True)
            click.echo("\nRe-authenticate with: perplexity-cli auth", err=True)
        elif status == 403:
            click.echo("✗ Access forbidden. Check your permissions.", err=True)
        elif status == 429:
            click.echo("✗ Rate limit exceeded. Please wait and try again later.", err=True)
        else:
            click.echo(f"✗ HTTP error {status}.", err=True)
            if ctx.obj.get("debug", False):
                click.echo(f"Details: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Export interrupted by user")
        click.echo("\n✗ Export interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error during export: {e}")
        click.echo(f"\n✗ Unexpected error: {e}", err=True)
        if ctx.obj.get("debug", False):
            import traceback

            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
