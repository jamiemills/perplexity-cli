"""Command-line interface for Perplexity CLI."""

import os
import sys
from pathlib import Path

import click

from perplexity_cli.utils.exceptions import (
    PerplexityHTTPStatusError,
    PerplexityRequestError,
)
from perplexity_cli.utils.logging import get_default_log_file, setup_logging


@click.group()
@click.version_option(package_name="pxcli")
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
    from perplexity_cli.auth.oauth_handler import authenticate_sync
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.utils.config import get_perplexity_base_url
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
        from perplexity_cli.utils.config import get_save_cookies_enabled

        tm = TokenManager()
        tm.save_token(token, cookies=cookies)
        logger.info(f"Token and cookies saved to {tm.token_path}")

        click.echo("[OK] Authentication successful!")
        click.echo(f"[OK] Token saved to: {tm.token_path}")

        # Show cookie message based on config
        if get_save_cookies_enabled():
            click.echo(f"[OK] {len(cookies)} cookies saved (including Cloudflare cookies)")
        else:
            click.echo("[INFO] Cookies not saved (disabled in config)")
            click.echo("  To enable cookie storage: pxcli set-config save_cookies true")

        click.echo('\nYou can now use: pxcli query "<your question>"')

    except TimeoutError as e:
        logger.error(f"Authentication timeout: {e}", exc_info=True)
        click.echo(f"[ERROR] Authentication timeout: {e}", err=True)
        click.echo("\nTroubleshooting:", err=True)
        click.echo(
            f"  1. Start Chrome with: --remote-debugging-port={port}",
            err=True,
        )
        click.echo(
            "  2. Ensure Chrome is running and accessible",
            err=True,
        )
        click.echo(
            f"  3. Navigate to {base_url} in Chrome",
            err=True,
        )
        click.echo("  4. Log in with your Google account", err=True)
        click.echo("  5. Run this command again", err=True)
        sys.exit(1)

    except RuntimeError as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        click.echo(f"[ERROR] Authentication failed: {e}", err=True)
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
        click.echo("\n[ERROR] Authentication interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error during authentication: {e}")
        click.echo(f"[ERROR] Unexpected error: {e}", err=True)
        if ctx.obj.get("debug", False):
            import traceback

            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@main.command()
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
@click.pass_context
def query(
    ctx: click.Context,
    query_text: str,
    output_format: str,
    strip_references: bool,
    stream: bool,
) -> None:
    """Submit a query to Perplexity.ai and get an answer.

    The answer is printed to stdout, making it easy to pipe to other commands.
    By default, responses are displayed after the complete response is fetched (batch mode). Use --stream for real-time streaming.

    Output formats:
        plain    - Plain text with underlined headers (good for scripts)
        markdown - GitHub-flavoured Markdown with proper structure
        rich     - Colourful terminal output with tables (default)
        json     - Structured JSON with answer and references

    Use --strip-references to remove all citations [1], [2], etc. and the
    references section from the output.

    Use --stream for real-time streaming of the response as it arrives.

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
    import logging

    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.api.streaming import stream_query_response
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.auth.utils import load_or_prompt_token
    from perplexity_cli.formatting import get_formatter, list_formatters
    from perplexity_cli.utils.http_errors import handle_http_error, handle_network_error
    from perplexity_cli.utils.logging import get_logger
    from perplexity_cli.utils.style_manager import StyleManager

    logger = get_logger()

    if logger.isEnabledFor(logging.DEBUG):
        import socket

        from perplexity_cli.utils.config import get_save_cookies_enabled

        # Debug: Log environment details at startup
        try:
            hostname = socket.gethostname()
            logger.debug(f"Hostname: {hostname}")
        except Exception:
            pass
        logger.debug(f"Platform: {sys.platform}")
        logger.debug(f"Python version: {sys.version.split()[0]}")
        logger.debug(f"Python executable: {sys.executable}")

        # Detect execution environment
        exec_env = "unknown"
        if hasattr(sys, "base_prefix"):
            if sys.base_prefix != sys.prefix:
                exec_env = "virtualenv"
        if "VIRTUAL_ENV" in os.environ:
            exec_env = "venv"
        if "UV_ACTIVE" in os.environ or "UVXENV" in os.environ:
            exec_env = "uvx"

        logger.debug(f"Execution environment: {exec_env}")

        # Log token and config paths
        token_path = Path.home() / ".config" / "perplexity-cli" / "token.json"
        logger.debug(f"Token path: {token_path}")
        logger.debug(f"Token exists: {token_path.exists()}")
        logger.debug(f"Cookie storage enabled: {get_save_cookies_enabled()}")

        logger.debug(
            f"Query command invoked: query='{query_text[:50]}...', format={output_format}, stream={stream}"
        )

    # Load token and cookies
    tm = TokenManager()
    token, cookies = load_or_prompt_token(tm, logger, command_context="query")

    try:
        # Determine output format
        output_format = output_format or "rich"

        # Get formatter instance
        try:
            formatter = get_formatter(output_format)
        except ValueError as e:
            click.echo(f"[ERROR] {e}", err=True)
            available = ", ".join(list_formatters())
            click.echo(f"Available formats: {available}", err=True)
            logger.error(f"Invalid formatter: {output_format}")
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
        with PerplexityAPI(token=token, cookies=cookies) as api:
            # Handle streaming vs complete answer
            if stream:
                logger.info("Streaming query response")
                stream_query_response(api, final_query, formatter, output_format, strip_references)
            else:
                logger.info("Fetching complete answer")
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

    except PerplexityHTTPStatusError as e:
        debug_mode = ctx.obj.get("debug", False) if ctx.obj else False
        handle_http_error(e, logger, debug_mode=debug_mode)

    except PerplexityRequestError as e:
        debug_mode = ctx.obj.get("debug", False) if ctx.obj else False
        handle_network_error(e, logger, debug_mode=debug_mode)

    except ValueError as e:
        logger.error(f"Value error: {e}")
        click.echo(f"[ERROR] Error: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Query interrupted by user")
        click.echo("\n[ERROR] Query interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        click.echo("[ERROR] An unexpected error occurred.", err=True)
        if ctx.obj.get("debug", False):
            import traceback

            click.echo(f"Debug info:\n{traceback.format_exc()}", err=True)
        else:
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
    from perplexity_cli.auth.token_manager import TokenManager

    tm = TokenManager()

    if not tm.token_exists():
        click.echo("No stored credentials found.")
        return

    try:
        tm.clear_token()
        click.echo("[OK] Logged out successfully.")
        click.echo("[OK] Stored credentials removed.")

    except Exception as e:
        from perplexity_cli.utils.logging import get_logger

        logger = get_logger()
        logger.error(f"Error during logout: {e}", exc_info=True)
        click.echo(f"[ERROR] Error during logout: {e}", err=True)
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


@main.command()
def view_style() -> None:
    """View currently configured style.

    Displays the style prompt that is being applied to queries, or a message
    if no style is configured.

    Example:
        perplexity-cli view-style
    """
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


@main.command()
def clear_style() -> None:
    """Clear configured style.

    Removes the style configuration. Queries will no longer have any style
    prompt appended.

    Example:
        perplexity-cli clear-style
    """
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


@main.command()
def status() -> None:
    """Show current authentication status.

    Displays whether you are authenticated and where the token is stored.
    Attempts to verify token validity by making a test query.

    Example:
        perplexity-cli status
    """
    from datetime import datetime

    from perplexity_cli.api.endpoints import PerplexityAPI
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()
    tm = TokenManager()

    click.echo("Perplexity CLI Status")
    click.echo("=" * 40)

    if tm.token_exists():
        try:
            token, cookies = tm.load_token()
            if token:
                click.echo("Status: [OK] Authenticated")
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
                    with PerplexityAPI(token=token, cookies=cookies, timeout=10) as api:
                        # Use a very short test query to verify token
                        test_answer = api.get_complete_answer("test")
                    if test_answer and len(test_answer.text) > 0:
                        click.echo("\n[OK] Token is valid and working")
                        logger.info("Token verification successful")
                    else:
                        click.echo("\n[INFO] Token verification returned empty response")
                        logger.warning("Token verification returned empty response")
                except PerplexityHTTPStatusError as e:
                    if e.response.status_code == 401:
                        click.echo("\n[ERROR] Token is invalid or expired")
                        logger.warning("Token verification failed: 401 Unauthorized")
                    else:
                        click.echo(
                            f"\n[INFO] Token verification failed (HTTP {e.response.status_code})"
                        )
                        logger.warning(f"Token verification failed: HTTP {e.response.status_code}")
                except Exception as e:
                    click.echo("\n[INFO] Token verification failed (unable to test)")
                    logger.debug(f"Token verification error: {e}", exc_info=True)

            else:
                click.echo("Status: [ERROR] Not authenticated")
        except RuntimeError as e:
            click.echo("Status: [INFO] Token file has insecure permissions")
            click.echo(f"Error: {e}")
            click.echo(f"\nFix with: chmod 0600 {tm.token_path}")
            logger.error(f"Token file has insecure permissions: {e}")
    else:
        click.echo("Status: [ERROR] Not authenticated")
        click.echo("\nAuthenticate with: pxcli auth")


@main.command(name="set-config")
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
    from perplexity_cli.utils.config import clear_feature_config_cache, set_feature
    from perplexity_cli.utils.logging import get_logger

    logger = get_logger()

    try:
        # Convert string to boolean
        bool_value = value.lower() == "true"

        # Update configuration
        set_feature(key, bool_value)

        # Clear cache to ensure new value is used
        clear_feature_config_cache()

        click.echo(f"[OK] Configuration updated: {key} = {bool_value}")
        logger.info(f"Configuration updated: {key} = {bool_value}")

        # Show helpful messages
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

    except RuntimeError as e:
        click.echo(f"[ERROR] Failed to update configuration: {e}", err=True)
        logger.error(f"Configuration update failed: {e}", exc_info=True)
        sys.exit(1)


@main.command(name="show-config")
@click.pass_context
def show_config(ctx: click.Context) -> None:
    """Display current configuration.

    Shows feature toggle settings and their sources.

    Example:
        pxcli show-config
    """
    from perplexity_cli.utils.config import get_feature_config, get_feature_config_path
    from perplexity_cli.utils.logging import get_logger

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

        # Show environment variable overrides if present
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

    except RuntimeError as e:
        click.echo(f"[ERROR] Failed to load configuration: {e}", err=True)
        logger.error(f"Configuration display failed: {e}", exc_info=True)
        sys.exit(1)


@main.command()
def show_skill() -> None:
    """Display the Agent Skill definition for using perplexity-cli.

    Shows the SKILL.md content that describes how to use perplexity-cli
    as an alternative to web search, including JSON output parsing examples
    and practical patterns for integration.

    Example:
        perplexity-cli show-skill
    """
    from importlib.resources import files

    try:
        skill_content = (
            files("perplexity_cli.resources").joinpath("skill.md").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, AttributeError):
        skill_content = "Agent Skill definition not available. Run 'perplexity-cli --help' for usage information."
    click.echo(skill_content)


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

    import httpx

    from perplexity_cli.auth.token_manager import TokenManager
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
        click.echo("[ERROR] Not authenticated.", err=True)
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
    if rate_limit_config.enabled:
        rate_limiter = RateLimiter(
            requests_per_period=rate_limit_config.requests_per_period,
            period_seconds=rate_limit_config.period_seconds,
        )
        logger.info(
            f"Rate limiting enabled: {rate_limit_config.requests_per_period} requests per "
            f"{rate_limit_config.period_seconds} seconds"
        )

    # Initialise cache manager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager

    cache_manager = ThreadCacheManager()

    # Handle cache deletion if requested
    if clear_cache:
        if cache_manager.cache_exists():
            cache_manager.clear_cache()
            click.echo("[OK] Cache cleared")
            logger.info("Cache cleared by user")
        else:
            click.echo("[INFO] No cache file to clear")

    # Validate date range if provided
    if from_date or to_date:
        try:
            from dateutil import parser as dateutil_parser

            if from_date:
                dateutil_parser.parse(from_date)
            if to_date:
                dateutil_parser.parse(to_date)
        except ValueError as e:
            click.echo(f"[ERROR] Invalid date format: {e}", err=True)
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
            click.echo("\n[ERROR] No threads found matching criteria.", err=True)
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
        click.echo("\n[OK] Export complete")
        click.echo(f"[OK] Exported {len(threads)} threads")
        if from_date or to_date:
            click.echo(
                f"[OK] Filtered by date range: {from_date or 'beginning'} to {to_date or 'end'}"
            )
        click.echo(f"[OK] Saved to: {output_path.resolve()}")

    except RuntimeError as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        click.echo(f"\n[ERROR] Export failed: {e}", err=True)
        if "Authentication failed" in str(e):
            click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
            click.echo("  perplexity-cli auth", err=True)
        sys.exit(1)

    except (PerplexityHTTPStatusError, httpx.HTTPStatusError) as e:
        status = e.response.status_code
        logger.error(f"HTTP error {status}: {e}")
        if status == 401:
            click.echo("[ERROR] Authentication failed. Token may be expired.", err=True)
            click.echo("\nRe-authenticate with: perplexity-cli auth", err=True)
        elif status == 403:
            click.echo("[ERROR] Access forbidden. Check your permissions.", err=True)
        elif status == 429:
            click.echo("[ERROR] Rate limit exceeded. Please wait and try again later.", err=True)
        else:
            click.echo(f"[ERROR] HTTP error {status}.", err=True)
            if ctx.obj.get("debug", False):
                click.echo(f"Details: {e}", err=True)
        sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Export interrupted by user")
        click.echo("\n[ERROR] Export interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        logger.exception(f"Unexpected error during export: {e}")
        click.echo(f"\n[ERROR] Unexpected error: {e}", err=True)
        if ctx.obj.get("debug", False):
            import traceback

            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
