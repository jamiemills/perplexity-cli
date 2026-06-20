"""Thread export command runner."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict, TypeGuard

import click

from perplexity_cli.envelope import success_envelope, write_envelope
from perplexity_cli.error_handler import handle_error

if TYPE_CHECKING:
    from perplexity_cli.threads.exporter import ThreadRecord
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
_EXPORT_TAIL_ARG_COUNT = 3

if TYPE_CHECKING:
    from perplexity_cli.auth.token_manager import TokenManager
    from perplexity_cli.config.models import RateLimitConfig
    from perplexity_cli.threads.cache_manager import ThreadCacheManager
    from perplexity_cli.threads.exporter import ThreadRecord
    from perplexity_cli.threads.scraper import ThreadScraper


class ExportContext(TypedDict, total=False):
    """Typed Click context flags used by the export runner."""

    json: bool
    schema: bool
    debug: bool


class ExportRateLimiterProtocol(Protocol):
    """Minimal rate-limiter surface used by the export runner."""

    async def acquire(self) -> float:
        """Wait for the next available request slot."""
        ...


DateRangePayload = TypedDict("DateRangePayload", {"from": str | None, "to": str | None})


class ThreadPayload(TypedDict):
    """JSON-serialisable thread summary for envelope output."""

    title: str
    created_at: str
    url: str


@dataclass(frozen=True, slots=True)
class ExportDateRange:
    """Requested date range for an export command."""

    from_date: str | None
    to_date: str | None


@dataclass(frozen=True, slots=True)
class OutputMode:
    """Output formatting flags for the export command."""

    json_mode: bool
    include_schema: bool


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """User-supplied export request parameters."""

    date_range: ExportDateRange
    output: Path | None
    force_refresh: bool
    clear_cache: bool


@dataclass(frozen=True, slots=True)
class PreparedExport:
    """Validated dependencies required to perform a thread export."""

    token: str
    cookies: dict[str, str] | None
    rate_limiter: ExportRateLimiterProtocol | None
    cache_manager: ThreadCacheManager
    output_mode: OutputMode
    logger: logging.Logger


@dataclass(frozen=True, slots=True)
class ExportResult:
    """Export output details for human and JSON presentation."""

    threads: list[ThreadRecord]
    output_path: Path | None
    date_range: ExportDateRange


def _create_token_manager() -> TokenManager:
    """Create the token manager used by this runner."""
    from perplexity_cli.auth.token_manager import TokenManager

    return TokenManager()


def _is_object_dict(value: object) -> TypeGuard[dict[object, object]]:
    """Return True when ``value`` is a plain dictionary."""
    return isinstance(value, dict)


def _is_object_mapping(value: object) -> TypeGuard[Mapping[object, object]]:
    """Return True when ``value`` is a mapping."""
    return isinstance(value, Mapping)


def _create_cache_manager() -> ThreadCacheManager:
    """Create the cache manager used by this runner."""
    from perplexity_cli.threads.cache_manager import ThreadCacheManager

    return ThreadCacheManager()


def _create_thread_scraper(
    prepared: PreparedExport,
    force_refresh: bool,
) -> ThreadScraper:
    """Create the thread scraper for the export workflow."""
    from perplexity_cli.threads.scraper import ThreadScraper

    return _call_scraper_factory(
        ThreadScraper,
        token=prepared.token,
        cookies=prepared.cookies,
        rate_limiter=prepared.rate_limiter,
        cache_manager=prepared.cache_manager,
        force_refresh=force_refresh,
    )


def _call_scraper_factory(
    factory: Callable[..., ThreadScraper],
    **kwargs: object,
) -> ThreadScraper:
    """Instantiate the scraper through a callable boundary."""
    return factory(**kwargs)


def _thread_payload(record: object) -> ThreadPayload:
    """Convert a thread-like object into JSON-envelope payload data."""
    if _is_object_dict(record):
        record_dict: dict[object, object] = record
        return {
            "title": _string_or_empty(record_dict.get("title", "")),
            "created_at": _string_or_empty(record_dict.get("created_at", "")),
            "url": _string_or_empty(record_dict.get("url", "")),
        }

    title = getattr(record, "title", "")
    created_at = getattr(record, "created_at", "")
    url = getattr(record, "url", "")
    return {
        "title": title if isinstance(title, str) else "",
        "created_at": created_at if isinstance(created_at, str) else "",
        "url": url if isinstance(url, str) else "",
    }


def _string_or_empty(value: object) -> str:
    """Return ``value`` when it is a string, else an empty string."""
    return value if isinstance(value, str) else ""


def _write_threads_csv(records: list[ThreadRecord], output_path: Path | None) -> Path:
    """Write thread rows to CSV through a typed boundary."""
    from perplexity_cli.threads.exporter import write_threads_csv

    return write_threads_csv(records, output_path)


def _normalise_context(ctx_obj: object) -> ExportContext | None:
    """Validate and narrow the Click context flags we rely on."""
    if ctx_obj is None:
        return None
    if not _is_object_mapping(ctx_obj):
        raise TypeError("ctx_obj must be a mapping or None")

    ctx_mapping: Mapping[object, object] = ctx_obj
    normalised: dict[str, object] = {}
    for key in ("json", "schema", "debug"):
        _store_context_flag(normalised, ctx_mapping, key)
    return ExportContext(
        json=bool(normalised.get("json")),
        schema=bool(normalised.get("schema")),
        debug=bool(normalised.get("debug")),
    )


def _build_export_request(
    from_date: object,
    to_date: object,
    args: tuple[object, ...],
    kwargs: Mapping[str, object],
) -> ExportRequest:
    """Validate and normalise export request parameters."""
    validated_from_date = _validate_optional_date(from_date, "from_date")
    validated_to_date = _validate_optional_date(to_date, "to_date")

    output, force_refresh, clear_cache = _resolve_export_tail_values(args, kwargs)
    validated_output = _validate_output_path(output)
    validated_force_refresh = _require_bool_value(force_refresh, "force_refresh")
    validated_clear_cache = _require_bool_value(clear_cache, "clear_cache")

    return ExportRequest(
        date_range=ExportDateRange(from_date=validated_from_date, to_date=validated_to_date),
        output=validated_output,
        force_refresh=validated_force_refresh,
        clear_cache=validated_clear_cache,
    )


def _require_output_path(output_path: Path | None) -> Path:
    """Return a guaranteed output path after CSV writing succeeds."""
    if output_path is None:
        raise RuntimeError("Output path should be available after export")
    return output_path


def _resolve_export_tail_values(
    args: tuple[object, ...],
    kwargs: Mapping[str, object],
) -> tuple[object | None, object, object]:
    """Extract ``output``, ``force_refresh``, and ``clear_cache`` values."""
    if args:
        return _resolve_export_tail_from_args(args, kwargs)
    return _resolve_export_tail_from_kwargs(kwargs)


def _resolve_export_tail_from_args(
    args: tuple[object, ...],
    kwargs: Mapping[str, object],
) -> tuple[object | None, object, object]:
    """Extract the trailing request values from positional arguments."""
    if kwargs or len(args) != _EXPORT_TAIL_ARG_COUNT:
        raise TypeError(
            "run_export_threads_command expected output, force_refresh, and clear_cache"
        )
    output, force_refresh, clear_cache = args
    return output, force_refresh, clear_cache


def _resolve_export_tail_from_kwargs(
    kwargs: Mapping[str, object],
) -> tuple[object | None, object, object]:
    """Extract the trailing request values from keyword arguments."""
    expected_keys = {"output", "force_refresh", "clear_cache"}
    if set(kwargs) != expected_keys:
        raise TypeError("run_export_threads_command requires output, force_refresh, clear_cache")
    return kwargs["output"], kwargs["force_refresh"], kwargs["clear_cache"]


def _store_context_flag(
    normalised: dict[str, object],
    ctx_mapping: Mapping[object, object],
    key: str,
) -> None:
    """Validate and store one optional boolean context flag."""
    value = ctx_mapping.get(key)
    if value is None:
        return
    if not isinstance(value, bool):
        raise TypeError(f"ctx_obj['{key}'] must be a bool when provided")
    normalised[key] = value


def _validate_optional_date(value: object, field_name: str) -> str | None:
    """Validate one optional date string argument."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    return value


def _validate_output_path(value: object) -> Path | None:
    """Validate one optional output path argument."""
    if value is None:
        return None
    if not isinstance(value, Path):
        raise TypeError("output must be a Path or None")
    return value


def _require_bool_value(value: object, field_name: str) -> bool:
    """Validate one required boolean argument."""
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _exit_with_date_error(  # nosemgrep: boolean-flag-argument
    e: ValueError, json_mode: bool
) -> None:
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


def _validate_export_dates(  # nosemgrep: boolean-flag-argument
    from_date: str | None, to_date: str | None, json_mode: bool
) -> None:
    """Validate date arguments, exiting on failure."""
    if not (from_date or to_date):
        return
    try:
        _parse_date(from_date)
        _parse_date(to_date)
    except ValueError as e:
        _exit_with_date_error(e, json_mode)


def _setup_rate_limiter(logger: logging.Logger) -> ExportRateLimiterProtocol | None:
    """Create a rate limiter if rate limiting is enabled, otherwise return None."""
    from perplexity_cli.utils.config import get_rate_limiting_config
    from perplexity_cli.utils.rate_limiter import RateLimiter

    config: RateLimitConfig = get_rate_limiting_config()
    if not config.enabled:
        return None
    logger.info(
        "Rate limiting enabled: %s requests per %s seconds",
        config.requests_per_period,
        config.period_seconds,
    )
    return RateLimiter(
        requests_per_period=config.requests_per_period,
        period_seconds=config.period_seconds,
    )


def _handle_cache_clear(  # nosemgrep: boolean-flag-argument
    cache_manager: ThreadCacheManager,
    clear_cache: bool,
    json_mode: bool,
    logger: logging.Logger,
) -> None:
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


def _scrape_threads(  # nosemgrep: boolean-flag-argument
    scraper: ThreadScraper,
    from_date: str | None,
    to_date: str | None,
    json_mode: bool,
) -> list[ThreadRecord]:
    """Run the thread scraper with a progress callback."""

    def update_progress(current: int, total: int) -> None:
        if not json_mode:
            click.echo(f"\rExtracting {current}/{total} threads...", nl=False)

    async def run_scrape() -> list[ThreadRecord]:
        return await scraper.scrape_all_threads(
            from_date=from_date,
            to_date=to_date,
            progress_callback=update_progress,
        )

    threads = run_async(run_scrape())
    if not json_mode:
        click.echo()
    return threads


def _handle_no_threads(  # nosemgrep: boolean-flag-argument
    from_date: str | None,
    to_date: str | None,
    json_mode: bool,
) -> None:
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


def _output_json(result: ExportResult, include_schema: bool) -> None:
    """Write JSON envelope output for export results."""
    output_path = _require_output_path(result.output_path)
    thread_items = [_thread_payload(thread) for thread in result.threads]
    env = success_envelope(
        _COMMAND,
        {
            "threads": thread_items,
            "total": len(result.threads),
            "output_path": str(output_path.resolve()),
            "date_range": {
                "from": result.date_range.from_date,
                "to": result.date_range.to_date,
            },
        },
    )
    write_envelope(env, include_schema=include_schema)


def _output_export_results(
    result: ExportResult, output_mode: OutputMode, logger: logging.Logger
) -> None:
    """Write CSV and output results in the appropriate format."""
    output_path = _write_threads_csv(result.threads, result.output_path)
    written_result = ExportResult(
        threads=result.threads,
        output_path=output_path,
        date_range=result.date_range,
    )
    logger.info("Exported %s threads to %s", len(result.threads), output_path)

    if output_mode.json_mode:
        _output_json(written_result, output_mode.include_schema)
        return

    click.echo("\n[OK] Export complete")
    click.echo(f"[OK] Exported {len(result.threads)} threads")
    _echo_date_range(result.date_range.from_date, result.date_range.to_date)
    click.echo(f"[OK] Saved to: {output_path.resolve()}")


def _handle_known_error(  # nosemgrep: boolean-flag-argument
    e: Exception, json_mode: bool, logger: logging.Logger
) -> None:
    """Handle AuthenticationError, PerplexityRequestError, UpstreamSchemaError, ValueError, and RateLimitError."""
    if json_mode:
        handle_error(e, command=_COMMAND, json_mode=True)
    logger.error("Export failed: %s", e, exc_info=True)
    click.echo(f"\n[ERROR] Export failed: {e}", err=True)
    if isinstance(e, AuthenticationError):
        click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
        click.echo("  perplexity-cli auth", err=True)
    sys.exit(1)


def _handle_http_status_error(  # nosemgrep: boolean-flag-argument
    e: PerplexityHTTPStatusError,
    json_mode: bool,
    ctx_obj: ExportContext | None,
    logger: logging.Logger,
) -> None:
    """Handle HTTP status errors from the Perplexity API."""
    if json_mode:
        handle_error(e, command=_COMMAND, json_mode=True)
    debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
    handle_http_error(e, logger, debug_mode=debug_mode, context="during thread export")


def _handle_unexpected_error(  # nosemgrep: boolean-flag-argument
    e: Exception,
    json_mode: bool,
    ctx_obj: ExportContext | None,
    logger: logging.Logger,
) -> None:
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


def _handle_auth_missing(  # nosemgrep: boolean-flag-argument
    json_mode: bool,
    logger: logging.Logger,
) -> None:
    """Handle missing authentication, exiting the process."""
    if json_mode:
        handle_error(
            AuthenticationError("Not authenticated"),
            command=_COMMAND,
            json_mode=True,
        )
    click.echo("[ERROR] Not authenticated.", err=True)
    click.echo("\nPlease authenticate first with: pxcli auth login", err=True)
    logger.warning("Export attempted without authentication")
    sys.exit(1)


def _resolve_ctx_flags(ctx_obj: ExportContext | None) -> OutputMode:
    """Extract json_mode and include_schema from the context object."""
    json_mode = ctx_obj.get("json", False) if ctx_obj else False
    include_schema = ctx_obj.get("schema", False) if ctx_obj else False
    return OutputMode(json_mode=json_mode, include_schema=include_schema)


def _prepare_export(  # nosemgrep: boolean-flag-argument
    ctx_obj: ExportContext | None,
    request: ExportRequest,
) -> PreparedExport:
    """Authenticate, validate dates, and build export dependencies."""
    logger: logging.Logger = get_logger()
    output_mode = _resolve_ctx_flags(ctx_obj)
    logger.info("Starting thread export")

    if not output_mode.json_mode:
        click.echo("Exporting threads from Perplexity.ai library...")

    tm = _create_token_manager()
    token, cookies = tm.load_token()
    if not token:
        _handle_auth_missing(output_mode.json_mode, logger)
        raise AssertionError("unreachable after auth-missing handler exits")

    _validate_export_dates(
        request.date_range.from_date,
        request.date_range.to_date,
        output_mode.json_mode,
    )
    rate_limiter: ExportRateLimiterProtocol | None = _setup_rate_limiter(logger)
    cache_manager: ThreadCacheManager = _create_cache_manager()
    _handle_cache_clear(cache_manager, request.clear_cache, output_mode.json_mode, logger)

    return PreparedExport(
        token=token,
        cookies=cookies,
        rate_limiter=rate_limiter,
        cache_manager=cache_manager,
        output_mode=output_mode,
        logger=logger,
    )


def _execute_scrape_and_export(prepared: PreparedExport, request: ExportRequest) -> None:
    """Create the scraper, scrape threads, and output results."""
    scraper = _create_thread_scraper(prepared, request.force_refresh)
    threads = _scrape_threads(
        scraper,
        request.date_range.from_date,
        request.date_range.to_date,
        prepared.output_mode.json_mode,
    )
    if not threads:
        _handle_no_threads(
            request.date_range.from_date,
            request.date_range.to_date,
            prepared.output_mode.json_mode,
        )
    _output_export_results(
        ExportResult(threads=threads, output_path=request.output, date_range=request.date_range),
        prepared.output_mode,
        prepared.logger,
    )


def run_export_threads_command(
    ctx_obj: object,
    from_date: str | None,
    to_date: str | None,
    *args: object,
    **kwargs: object,
) -> None:
    """Execute the export-threads command."""
    typed_ctx_obj = _normalise_context(ctx_obj)
    request = _build_export_request(from_date, to_date, args, kwargs)
    prepared = _prepare_export(typed_ctx_obj, request)

    try:
        _execute_scrape_and_export(prepared, request)
    except KeyboardInterrupt:
        prepared.logger.info("Export interrupted by user")
        click.echo("\n[ERROR] Export interrupted.", err=True)
        sys.exit(130)
    except (
        AuthenticationError,
        PerplexityRequestError,
        UpstreamSchemaError,
        ValueError,
        RateLimitError,
    ) as e:
        _handle_known_error(e, prepared.output_mode.json_mode, prepared.logger)
    except PerplexityHTTPStatusError as e:
        _handle_http_status_error(e, prepared.output_mode.json_mode, typed_ctx_obj, prepared.logger)
    except Exception as e:
        _handle_unexpected_error(
            e,
            prepared.output_mode.json_mode,
            typed_ctx_obj,
            prepared.logger,
        )
