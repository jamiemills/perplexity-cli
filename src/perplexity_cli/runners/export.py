"""Thread export command runner."""

import sys
from pathlib import Path

import click

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


def run_export_threads_command(
    ctx_obj: dict | None,
    from_date: str | None,
    to_date: str | None,
    output: Path | None,
    force_refresh: bool,
    clear_cache: bool,
) -> None:
    """Execute the export-threads command."""
    from dateutil import parser as dateutil_parser

    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.threads.exporter import write_threads_csv
    from perplexity_cli.threads.scraper import ThreadScraper
    from perplexity_cli.utils.config import get_rate_limiting_config
    from perplexity_cli.utils.rate_limiter import RateLimiter

    logger = get_logger()
    logger.info("Starting thread export")
    click.echo("Exporting threads from Perplexity.ai library...")

    tm = TokenManager()
    token, cookies = tm.load_token()
    if not token:
        click.echo("[ERROR] Not authenticated.", err=True)
        click.echo("\nPlease authenticate first with: pxcli auth", err=True)
        logger.warning("Export attempted without authentication")
        sys.exit(1)

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

    cache_manager = ThreadCacheManager()
    if clear_cache:
        if cache_manager.cache_exists():
            cache_manager.clear_cache()
            click.echo("[OK] Cache cleared")
            logger.info("Cache cleared by user")
        else:
            click.echo("[INFO] No cache file to clear")

    if from_date or to_date:
        try:
            if from_date:
                dateutil_parser.parse(from_date)
            if to_date:
                dateutil_parser.parse(to_date)
        except ValueError as e:
            click.echo(f"[ERROR] Invalid date format: {e}", err=True)
            click.echo("Please use YYYY-MM-DD format (e.g., 2025-12-23)", err=True)
            sys.exit(1)

    try:
        scraper = ThreadScraper(
            token=token,
            cookies=cookies,
            rate_limiter=rate_limiter,
            cache_manager=cache_manager,
            force_refresh=force_refresh,
        )

        def update_progress(current: int, total: int) -> None:
            click.echo(f"\rExtracting {current} threads...", nl=False)

        async def run_scrape() -> list:
            return await scraper.scrape_all_threads(
                from_date=from_date,
                to_date=to_date,
                progress_callback=update_progress,
            )

        threads = run_async(run_scrape())
        click.echo()

        if not threads:
            click.echo("\n[ERROR] No threads found matching criteria.", err=True)
            if from_date or to_date:
                click.echo(
                    f"Date range: {from_date or 'beginning'} to {to_date or 'end'}",
                    err=True,
                )
            sys.exit(1)

        output_path = write_threads_csv(threads, output)
        logger.info(f"Exported {len(threads)} threads to {output_path}")

        click.echo("\n[OK] Export complete")
        click.echo(f"[OK] Exported {len(threads)} threads")
        if from_date or to_date:
            click.echo(
                f"[OK] Filtered by date range: {from_date or 'beginning'} to {to_date or 'end'}"
            )
        click.echo(f"[OK] Saved to: {output_path.resolve()}")

    except (AuthenticationError, PerplexityRequestError, UpstreamSchemaError, ValueError) as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        click.echo(f"\n[ERROR] Export failed: {e}", err=True)
        if "Authentication failed" in str(e):
            click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
            click.echo("  perplexity-cli auth", err=True)
        sys.exit(1)

    except RateLimitError as e:
        logger.error(f"Export rate limited: {e}", exc_info=True)
        click.echo(f"\n[ERROR] Export failed: {e}", err=True)
        sys.exit(1)

    except PerplexityHTTPStatusError as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_http_error(e, logger, debug_mode=debug_mode, context="during thread export")

    except KeyboardInterrupt:
        logger.info("Export interrupted by user")
        click.echo("\n[ERROR] Export interrupted.", err=True)
        sys.exit(130)

    except Exception as e:
        debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
        handle_unexpected_cli_error(
            e,
            logger,
            debug_mode=debug_mode,
            user_message=f"\n[ERROR] Unexpected error: {e}",
            log_message="Unexpected error during export",
        )
