"""Thread export command runner."""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict, TypeGuard

import click

from perplexity_cli._types import OutputFormat, SchemaInclusion
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

    json_mode: OutputFormat
    include_schema: SchemaInclusion


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


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------


def _create_token_manager() -> TokenManager:
    """Create the token manager used by this runner."""
    from perplexity_cli.auth.token_manager import TokenManager

    return TokenManager()


def _emit_json_error(e: Exception, output_format: OutputFormat) -> None:
    """Emit ``e`` as a JSON error envelope when in JSON output mode."""
    if output_format == "json":
        handle_error(e, _COMMAND, output_format="json")


def _create_cache_manager() -> ThreadCacheManager:
    """Create the cache manager used by this runner."""
    from perplexity_cli.threads.cache_manager import ThreadCacheManager

    return ThreadCacheManager()


def _is_dict_str_obj(v: object) -> TypeGuard[dict[str, object]]:
    return isinstance(v, dict)


def _thread_payload(record: object) -> ThreadPayload:
    """Convert a thread-like object into JSON-envelope payload data."""
    if _is_dict_str_obj(record):
        return {
            "title": _string_or_empty(record.get("title", "")),
            "created_at": _string_or_empty(record.get("created_at", "")),
            "url": _string_or_empty(record.get("url", "")),
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


def _normalise_context(ctx_obj: object) -> ExportContext | None:
    """Validate and narrow the Click context flags we rely on."""
    if not _is_dict_str_obj(ctx_obj):
        return None

    normalised: dict[str, object] = {}
    for key in ("json", "schema", "debug"):
        value = ctx_obj.get(key)
        if value is None:
            continue
        if not isinstance(value, bool):
            raise TypeError(f"ctx_obj['{key}'] must be a bool when provided")
        normalised[key] = value
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


def _resolve_export_tail_values(
    args: tuple[object, ...],
    kwargs: Mapping[str, object],
) -> tuple[object | None, object, object]:
    """Extract ``output``, ``force_refresh``, and ``clear_cache`` values."""
    if kwargs:
        expected_keys = {"output", "force_refresh", "clear_cache"}
        if set(kwargs) != expected_keys:
            raise TypeError(
                "run_export_threads_command requires output, force_refresh, clear_cache"
            )
        return kwargs["output"], kwargs["force_refresh"], kwargs["clear_cache"]
    if len(args) != _EXPORT_TAIL_ARG_COUNT:
        raise TypeError(
            "run_export_threads_command expected output, force_refresh, and clear_cache"
        )
    output, force_refresh, clear_cache = args
    return output, force_refresh, clear_cache


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


def _validate_export_dates(
    from_date: str | None, to_date: str | None, output_format: OutputFormat
) -> None:
    """Validate date arguments, exiting on failure."""
    if not (from_date or to_date):
        return
    try:
        _try_parse_dates(from_date, to_date)
    except ValueError as e:
        _emit_json_error(e, output_format)
        click.echo(f"[ERROR] Invalid date format: {e}", err=True)
        click.echo("Please use YYYY-MM-DD format (e.g., 2025-12-23)", err=True)
        sys.exit(1)


def _try_parse_dates(from_date: str | None, to_date: str | None) -> None:
    """Parse date strings, raising ValueError if either is invalid."""
    from dateutil import parser as dateutil_parser

    for date_str in (from_date, to_date):
        if date_str:
            dateutil_parser.parse(date_str)


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


# ---------------------------------------------------------------------------
# Export pipeline
# ---------------------------------------------------------------------------


def _handle_cache_clear(
    cache_manager: ThreadCacheManager,
    clear_cache: bool,
    output_format: OutputFormat,
    logger: logging.Logger,
) -> None:
    """Clear the thread cache if requested."""
    if not clear_cache:
        return
    if not cache_manager.cache_exists():
        if output_format != "json":
            click.echo("[INFO] No cache file to clear")
        return
    cache_manager.clear_cache()
    if output_format != "json":
        click.echo("[OK] Cache cleared")
    logger.info("Cache cleared by user")


def _scrape_threads(
    scraper: ThreadScraper,
    from_date: str | None,
    to_date: str | None,
    output_format: OutputFormat,
) -> list[ThreadRecord]:
    """Run the thread scraper with a progress callback."""

    def update_progress(current: int, total: int) -> None:
        if output_format != "json":
            click.echo(f"\rExtracting {current}/{total} threads...", nl=False)

    threads = run_async(
        scraper.scrape_all_threads(
            from_date=from_date,
            to_date=to_date,
            progress_callback=update_progress,
        )
    )
    if output_format != "json":
        click.echo()
    return threads


def _handle_no_threads(
    from_date: str | None,
    to_date: str | None,
    output_format: OutputFormat,
) -> None:
    """Handle the case where no threads were found, exiting the process."""
    _emit_json_error(ValueError("No threads found matching criteria"), output_format)
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


def _output_json(result: ExportResult, include_schema: SchemaInclusion) -> None:
    """Write JSON envelope output for export results."""
    output_path = result.output_path
    if output_path is None:
        raise RuntimeError("Output path should be available after export")
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
    from perplexity_cli.threads.exporter import write_threads_csv

    output_path = write_threads_csv(result.threads, result.output_path)
    written_result = ExportResult(
        threads=result.threads,
        output_path=output_path,
        date_range=result.date_range,
    )
    logger.info("Exported %s threads to %s", len(result.threads), output_path)

    if output_mode.json_mode == "json":
        _output_json(written_result, output_mode.include_schema)
        return

    click.echo("\n[OK] Export complete")
    click.echo(f"[OK] Exported {len(result.threads)} threads")
    _echo_date_range(result.date_range.from_date, result.date_range.to_date)
    click.echo(f"[OK] Saved to: {output_path.resolve()}")


def _handle_known_error(e: Exception, output_format: OutputFormat, logger: logging.Logger) -> None:
    """Handle AuthenticationError, PerplexityRequestError, UpstreamSchemaError, ValueError, and RateLimitError."""
    _emit_json_error(e, output_format)
    logger.error("Export failed: %s", e, exc_info=True)
    click.echo(f"\n[ERROR] Export failed: {e}", err=True)
    if isinstance(e, AuthenticationError):
        click.echo("\nYour token may have expired. Please re-authenticate:", err=True)
        click.echo("  perplexity-cli auth", err=True)
    sys.exit(1)


def _handle_http_status_error(
    e: PerplexityHTTPStatusError,
    output_format: OutputFormat,
    ctx_obj: ExportContext | None,
    logger: logging.Logger,
) -> None:
    """Handle HTTP status errors from the Perplexity API."""
    _emit_json_error(e, output_format)
    debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
    handle_http_error(
        e, logger, debug_mode="debug" if debug_mode else "normal", context="during thread export"
    )


def _handle_unexpected_error(
    e: Exception,
    output_format: OutputFormat,
    ctx_obj: ExportContext | None,
    logger: logging.Logger,
) -> None:
    """Handle unexpected errors during export."""
    _emit_json_error(e, output_format)
    debug_mode = ctx_obj.get("debug", False) if ctx_obj else False
    handle_unexpected_cli_error(
        e,
        logger,
        debug_mode="debug" if debug_mode else "normal",
        message_tuple=(f"\n[ERROR] Unexpected error: {e}", "Unexpected error during export", False),
    )


def _handle_auth_missing(
    output_format: OutputFormat,
    logger: logging.Logger,
) -> None:
    """Handle missing authentication, exiting the process."""
    _emit_json_error(AuthenticationError("Not authenticated"), output_format)
    click.echo("[ERROR] Not authenticated.", err=True)
    click.echo("\nPlease authenticate first with: pxcli auth login", err=True)
    logger.warning("Export attempted without authentication")
    sys.exit(1)


def _resolve_ctx_flags(ctx_obj: ExportContext | None) -> OutputMode:
    """Extract json_mode and include_schema from the context object."""
    return OutputMode(
        json_mode="json" if (ctx_obj and ctx_obj.get("json")) else "human",
        include_schema="with_schema" if (ctx_obj and ctx_obj.get("schema")) else "no_schema",
    )


def _prepare_export(
    ctx_obj: ExportContext | None,
    request: ExportRequest,
) -> PreparedExport:
    """Authenticate, validate dates, and build export dependencies."""
    logger: logging.Logger = get_logger()
    output_mode = _resolve_ctx_flags(ctx_obj)
    logger.info("Starting thread export")

    if output_mode.json_mode != "json":
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
    from perplexity_cli.threads.scraper import ThreadScraper

    scraper = ThreadScraper(
        token=prepared.token,
        cookies=prepared.cookies,
        rate_limiter=prepared.rate_limiter,
        cache_manager=prepared.cache_manager,
        force_refresh=request.force_refresh,
    )
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
