"""Thread export command runner."""

import sys
from pathlib import Path

import click

from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error
from perplexity_cli.utils.async_bridge import run_async
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import handle_http_error, handle_unexpected_cli_error
from perplexity_cli.utils.logging import get_logger

_COMMAND = "pxcli threads export"


def _exit_with_date_error(e: ValueError, json_mode: bool) -> None:
    """Report a date validation error and exit."""
    if json_mode:
        handle_error(e, command=_COMMAND, json_mode=True)
    click.echo(f"[ERROR] Invalid date format: {e}", err=True)
    click.echo("Please use YYYY-MM-DD format (e.g., 2025-12-23)", err=True)
    sys.exit(1)


def _parse_date(date_str: str | None) -> None:
    """Parse a single date string, raising ValueError if invalid."""
    from dateutil import parser as dateutil_parser

    if date_str:
        dateutil_parser.parse(date_str)


def _validate_export_dates(from_date: str | None, to_date: str | None, json_mode: bool) -> None:
    """Validate date arguments, exiting on failure."""
    if not (from_date or to_date):
        return
    try:
        _parse_date(from_date)
        _parse_date(to_date)
    except ValueError as e:
        _exit_with_date_error(e, json_mode)


def _setup_rate_limiter(logger):
    """Create a rate limiter if rate limiting is enabled, otherwise return None."""
    from perplexity_cli.utils.config import get_rate_limiting_config
    from perplexity_cli.utils.rate_limiter import RateLimiter

    config = get_rate_limiting_config()
    if not config.enabled:
        return None
    logger.info(
        f"Rate limiting enabled: {config.requests_per_period} requests per "
        f"{config.period_seconds} seconds"
    )
    return RateLimiter(
        requests_per_period=config.requests_per_period,
        period_seconds=config.period_seconds,
    )


def _handle_cache_clear(cache_manager, clear_cache: bool, json_mode: bool, logger) -> None:
    """Clear the thread cache if requested."""
    if not clear_cache:
        return
    if not cache_manager.cache_exists():
        if not json_mode:
            click.echo("[INFO] No cache file to clear")
        return
    cache_manager.clear_cache()
    if not json_mode:
        click.echo("[OK] Cache cleared")
    logger.info("Cache cleared by user")


def _scrape_threads(scraper, from_date, to_date, json_mode: bool) -> list:
    """Run the thread scraper with a progress callback."""

    def update_progress(current: int, total: int) -> None:
        if not json_mode:
            click.echo(f"\rExtracting {current}/{total} threads...", nl=False)

    async def run_scrape() -> list:
        return await scraper.scrape_all_threads(
            from_date=from_date,
            to_date=to_date,
            progress_callback=update_progress,
        )

    threads = run_async(run_scrape())
    if not json_mode:
        click.echo()
    return threads


def _handle_no_threads(from_date, to_date, json_mode: bool) -> None:
    """Handle the case where no threads were found, exiting the process."""
    if json_mode:
        handle_error(
            ValueError("No threads found matching criteria"),
            command=_COMMAND,
            json_mode=True,
        )
    click.echo("\n[ERROR] No threads found matching criteria.", err=True)
    _echo_date_range(from_date, to_date, prefix="Date range")
    sys.exit(1)


def _echo_date_range(
    from_date: str | None, to_date: str | None, *, prefix: str = "[OK] Filtered by date range"
) -> None:
    """Print the date range to stderr if either date is set."""
    if from_date or to_date:
        click.echo(
            f"{prefix}: {from_date or 'beginning'} to {to_date or 'end'}",
            err=True,
        )


def _output_json(  # nosemgrep: too-many-parameters
    threads, output_path, from_date, to_date, include_schema
) -> None:
    """Write JSON envelope output for export results."""
    thread_items = [
        {
            "title": t.get("title", ""),
            "created_at": t.get("created_at", ""),
            "url": t.get("url", ""),
        }
        for t in threads
    ]
    env = success_envelope(
        _COMMAND,
        {
            "threads": thread_items,
            "total": len(threads),
            "output_path": str(output_path.resolve()),
            "date_range": {"from": from_date, "to": to_date},
        },
    )
    write_envelope(env, include_schema=include_schema)


def _output_export_results(  # nosemgrep: too-many-parameters
    threads: list,
    output: Path | None,
    from_date: str | None,
    to_date: str | None,
    json_mode: bool,
    include_schema: bool,
    logger,
) -> None:
    """Write CSV and output results in the appropriate format."""
    from perplexity_cli.threads.exporter import write_threads_csv

    output_path = write_threads_csv(threads, output)
    logger.info("Exported %s threads to %s", len(threads), output_path)

    if json_mode:
        _output_json(threads, output_path, from_date, to_date, include_schema)
        return

    click.echo("\n[OK] Export complete")
    click.echo(f"[OK] Exported {len(threads)} threads")
    _echo_date_range(from_date, to_date)
    click.echo(f"[OK] Saved to: {output_path.resolve()}")


def _handle_known_error(e: Exception, json_mode: bool, logger) -> None:
    """Handle AuthenticationError, PerplexityRequestError, UpstreamSchemaError, ValueError, and RateLimitError."""
    if json_mode:
        handle_error(e, command=_COMMAND, json_mode=True)
    logger.error(f"Export failed: {e}", exc_info=True)
    click.echo(f"\n[ERROR] Export failed: {e}", err=True)
    if isinstance(e, AuthenticationError):
        click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
        click.echo("  perplexity-cli auth", err=True)
    sys.exit(1)


def _handle_http_status_error(
    e: PerplexityHTTPStatusError, json_mode: bool, ctx_obj: dict | None, logger
) -> None:
    """Handle HTTP status errors from the Perplexity API."""
    if json_mode:
        handle_error(e, command=_COMMAND, json_mode=True)
    debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
    handle_http_error(e, logger, debug_mode=debug_mode, context="during thread export")


def _handle_unexpected_error(e: Exception, json_mode: bool, ctx_obj: dict | None, logger) -> None:
    """Handle unexpected errors during export."""
    if json_mode:
        handle_error(e, command=_COMMAND, json_mode=True)
    debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
    handle_unexpected_cli_error(
        e,
        logger,
        debug_mode=debug_mode,
        user_message=f"\n[ERROR] Unexpected error: {e}",
        log_message="Unexpected error during export",
    )


def _handle_auth_missing(json_mode: bool, logger) -> None:
    """Handle missing authentication, exiting the process."""
    if json_mode:
        handle_error(
            AuthenticationError("Not authenticated"),
            command=_COMMAND,
            json_mode=True,
        )
    click.echo("[ERROR] Not authenticated.", err=True)
    click.echo("\nPlease authenticate first with: pxcli auth", err=True)
    logger.warning("Export attempted without authentication")
    sys.exit(1)


def _resolve_ctx_flags(ctx_obj: dict | None) -> tuple[bool, bool]:
    """Extract json_mode and include_schema from the context object."""
    json_mode = ctx_obj.get("json", False) if ctx_obj else False
    include_schema = ctx_obj.get("schema", False) if ctx_obj else False
    return json_mode, include_schema


def _prepare_export(ctx_obj: dict | None, from_date, to_date, clear_cache: bool):
    """Authenticate, validate dates, set up rate limiter and cache. Returns (token, cookies, rate_limiter, cache_manager, json_mode, include_schema, logger)."""
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager

    logger = get_logger()
    json_mode, include_schema = _resolve_ctx_flags(ctx_obj)
    logger.info("Starting thread export")

    if not json_mode:
        click.echo("Exporting threads from Perplexity.ai library...")

    tm = TokenManager()
    token, cookies = tm.load_token()
    if not token:
        _handle_auth_missing(json_mode, logger)

    _validate_export_dates(from_date, to_date, json_mode)
    rate_limiter = _setup_rate_limiter(logger)
    cache_manager = ThreadCacheManager()
    _handle_cache_clear(cache_manager, clear_cache, json_mode, logger)

    return token, cookies, rate_limiter, cache_manager, json_mode, include_schema, logger


def _execute_scrape_and_export(  # nosemgrep: too-many-parameters
    token,
    cookies,
    rate_limiter,
    cache_manager,
    force_refresh,
    from_date,
    to_date,
    output,
    json_mode,
    include_schema,
    logger,
) -> None:
    """Create the scraper, scrape threads, and output results."""
    from perplexity_cli.threads.scraper import ThreadScraper

    scraper = ThreadScraper(
        token=token,
        cookies=cookies,
        rate_limiter=rate_limiter,
        cache_manager=cache_manager,
        force_refresh=force_refresh,
    )
    threads = _scrape_threads(scraper, from_date, to_date, json_mode)
    if not threads:
        _handle_no_threads(from_date, to_date, json_mode)
    _output_export_results(threads, output, from_date, to_date, json_mode, include_schema, logger)


def run_export_threads_command(  # nosemgrep: too-many-parameters
    ctx_obj: dict | None,
    from_date: str | None,
    to_date: str | None,
    output: Path | None,
    force_refresh: bool,
    clear_cache: bool,
) -> None:
    """Execute the export-threads command."""
    token, cookies, rate_limiter, cache_manager, json_mode, include_schema, logger = (
        _prepare_export(ctx_obj, from_date, to_date, clear_cache)
    )

    try:
        _execute_scrape_and_export(
            token,
            cookies,
            rate_limiter,
            cache_manager,
            force_refresh,
            from_date,
            to_date,
            output,
            json_mode,
            include_schema,
            logger,
        )
    except KeyboardInterrupt:
        logger.info("Export interrupted by user")
        click.echo("\n[ERROR] Export interrupted.", err=True)
        sys.exit(130)
    except (
        AuthenticationError,
        PerplexityRequestError,
        UpstreamSchemaError,
        ValueError,
        RateLimitError,
    ) as e:
        _handle_known_error(e, json_mode, logger)
    except PerplexityHTTPStatusError as e:
        _handle_http_status_error(e, json_mode, ctx_obj, logger)
    except Exception as e:
        _handle_unexpected_error(e, json_mode, ctx_obj, logger)
