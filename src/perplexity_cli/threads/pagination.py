"""Pagination, date-range, and progress helpers for the thread scraper.

Extracted from ``threads/scraper.py`` to keep that module under the 1000-line
file-size cap.  The extraction is behaviour-identical; ``threads/scraper.py``
re-exports these helpers so its domain-test API is unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol, TypeGuard

from perplexity_cli.threads.date_parser import is_in_date_range, to_iso8601
from perplexity_cli.threads.models import validate_date_args
from perplexity_cli.utils.exceptions import UpstreamSchemaError

# The (underscore-prefixed) helper names are exported so ``threads/scraper.py``
# can re-export them without tripping pyright's reportPrivateUsage rule.
__all__ = [
    "_LEGACY_CONTEXT_ARG_LIMIT",
    "_PROGRESS_CALLBACK_ARG_INDEX",
    "_THREAD_PAGE_SIZE",
    "_TOTAL_THREADS_ARG_INDEX",
    "BatchProcessingContext",
    "PaginationState",
    "ProgressCallback",
    "ThreadPayload",
    "_build_batch_processing_context",
    "_build_legacy_batch_processing_context",
    "_coerce_optional_int",
    "_coerce_optional_str",
    "_coerce_progress_callback",
    "_extract_total_threads",
    "_has_more_pages",
    "_is_in_date_range",
    "_is_progress_callback",
    "_legacy_context_value",
    "_next_pagination_offset",
    "_page_signature",
    "_report_progress",
    "_to_iso8601",
    "_validate_batch_processing_arg_count",
    "_validate_date_params",
]

_THREAD_PAGE_SIZE: Final = 100
_LEGACY_CONTEXT_ARG_LIMIT: Final = 3
_TOTAL_THREADS_ARG_INDEX: Final = 1
_PROGRESS_CALLBACK_ARG_INDEX: Final = 2


class ProgressCallback(Protocol):
    """Protocol for scrape progress notifications."""

    def __call__(self, current: int, total: int) -> None:
        """Report the current and total thread counts."""


ThreadPayload = dict[str, object]


@dataclass(frozen=True, slots=True)
class BatchProcessingContext:
    """Per-batch state for thread payload processing."""

    from_date: str | None = None
    total_threads: int | None = None
    progress_callback: ProgressCallback | None = None


@dataclass(frozen=True, slots=True)
class PaginationState:
    """Pagination cursor state for the private thread-list protocol."""

    offset: int = 0
    limit: int = _THREAD_PAGE_SIZE
    previous_signature: str | None = None


def _is_progress_callback(value: object) -> TypeGuard[ProgressCallback]:
    """Return True when a runtime object can be used as a progress callback."""
    return callable(value)


def _coerce_optional_str(value: object, field_name: str) -> str | None:
    """Validate an optional string argument parsed from a legacy call shape."""
    if value is None or isinstance(value, str):
        return value
    msg = f"{field_name} must be a string or None"
    raise TypeError(msg)


def _coerce_optional_int(value: object, field_name: str) -> int | None:
    """Validate an optional integer argument parsed from a legacy call shape."""
    if value is None or isinstance(value, int):
        return value
    msg = f"{field_name} must be an integer or None"
    raise TypeError(msg)


def _coerce_progress_callback(value: object) -> ProgressCallback | None:
    """Validate an optional progress callback parsed from a legacy call shape."""
    if value is None:
        return None
    if _is_progress_callback(value):
        return value
    msg = "progress_callback must be callable or None"
    raise TypeError(msg)


def _validate_batch_processing_arg_count(arg_count: int) -> None:
    """Validate the legacy batch-processing argument count."""
    if arg_count > _LEGACY_CONTEXT_ARG_LIMIT:
        msg = "_process_thread_batch expected at most three context arguments"
        raise TypeError(msg)


def _legacy_context_value(args: tuple[object, ...], index: int) -> object | None:
    """Return one legacy batch-processing argument or ``None`` when absent."""
    if len(args) > index:
        return args[index]
    return None


def _build_legacy_batch_processing_context(
    args: tuple[object, ...],
) -> BatchProcessingContext:
    """Build a typed batch-processing context from the legacy call shape."""
    from_date = _coerce_optional_str(_legacy_context_value(args, 0), "from_date")
    total_threads = _coerce_optional_int(
        _legacy_context_value(args, _TOTAL_THREADS_ARG_INDEX),
        "total_threads",
    )
    progress_callback = _coerce_progress_callback(
        _legacy_context_value(args, _PROGRESS_CALLBACK_ARG_INDEX)
    )
    return BatchProcessingContext(
        from_date=from_date,
        total_threads=total_threads,
        progress_callback=progress_callback,
    )


def _build_batch_processing_context(*args: object) -> BatchProcessingContext:
    """Normalise batch-processing arguments into a typed context object."""
    if not args:
        return BatchProcessingContext()
    if len(args) == 1 and isinstance(args[0], BatchProcessingContext):
        return args[0]
    _validate_batch_processing_arg_count(len(args))
    return _build_legacy_batch_processing_context(args)


def _is_in_date_range(dt: datetime, from_date: str | None, to_date: str | None) -> bool:
    """Proxy the date-range check through the shared date parser."""
    return is_in_date_range(dt, from_date, to_date)


def _to_iso8601(dt: datetime) -> str:
    """Proxy ISO-8601 formatting through the shared date parser."""
    return to_iso8601(dt)


def _validate_date_params(from_date: str | None, to_date: str | None) -> None:
    """Validate that from_date and to_date are strict YYYY-MM-DD strings.

    Args:
        from_date: Start date string to validate (or None).
        to_date: End date string to validate (or None).

    Raises:
        ValueError: If either date string is not YYYY-MM-DD, or from_date
            is after to_date.
    """
    validate_date_args(from_date, to_date)


def _extract_total_threads(thread_dict: ThreadPayload, total_threads: int | None) -> int:
    """Extract the total thread count from an API response entry."""
    if total_threads is not None:
        return total_threads
    raw = thread_dict.get("total_threads", 0)
    if not isinstance(raw, int):
        msg = "Malformed total_threads value in upstream API response"
        raise UpstreamSchemaError(msg)
    return raw


def _has_more_pages(thread_data: list[ThreadPayload]) -> bool:
    """Check whether the API response indicates more pages are available.

    The first record is authoritative; flags on later records are ignored.
    Non-boolean flag values are treated as a malformed upstream schema.

    Args:
        thread_data: Thread dictionaries from the current page.

    Returns:
        True if a next page exists.

    Raises:
        UpstreamSchemaError: If the first record's has_next_page is not a boolean.
    """
    if not thread_data:
        return False
    has_next = thread_data[0].get("has_next_page", False)
    if not isinstance(has_next, bool):
        msg = "Malformed has_next_page value in upstream API response"
        raise UpstreamSchemaError(msg)
    return has_next


def _page_signature(thread_data: list[ThreadPayload]) -> str:
    """Build a signature for a paginated page based on its first record.

    Args:
        thread_data: Thread dictionaries from the current page.

    Returns:
        A signature string identifying the page's first record.
    """
    first = thread_data[0]
    return f"{first.get('last_query_datetime')}|{first.get('slug')}"


def _next_pagination_offset(offset: int, limit: int) -> int:
    """Compute the next pagination offset, guarding against non-advancement.

    Args:
        offset: Current pagination offset.
        limit: Current page size.

    Returns:
        The next pagination offset.

    Raises:
        UpstreamSchemaError: If the next offset would not advance beyond the
            current offset.
    """
    next_offset = offset + limit
    if next_offset <= offset:
        msg = "Non-advancing pagination offset in upstream API response"
        raise UpstreamSchemaError(msg)
    return next_offset


def _report_progress(
    callback: Callable[[int, int], None] | None,
    current: int,
    total: int | None,
) -> None:
    """Invoke progress callback if available.

    Args:
        callback: Optional progress callback.
        current: Current number of threads processed.
        total: Total expected threads, or None if unknown.
    """
    if callback and total:
        callback(current, total)
