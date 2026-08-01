"""Pydantic models and date helpers for thread cache management."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import TypeGuard

from pydantic import BaseModel, Field, field_validator

_DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_strict_date(date_str: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date string.

    Args:
        date_str: Date string in ``YYYY-MM-DD`` format.

    Returns:
        The parsed date.

    Raises:
        ValueError: If the string is not exactly ``YYYY-MM-DD`` or is not a
            real calendar date.
    """
    if _DATE_ONLY_RE.fullmatch(date_str) is None:
        msg = f"Invalid date '{date_str}': expected YYYY-MM-DD format"
        raise ValueError(msg)
    try:
        year, month, day = (int(part) for part in date_str.split("-"))
        return date(year, month, day)
    except ValueError as exc:
        msg = f"Invalid date '{date_str}': expected YYYY-MM-DD format"
        raise ValueError(msg) from exc


def parse_iso8601_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp string strictly.

    Accepts timestamps produced by the thread exporter, such as
    ``2025-12-23T13:51:50Z`` or ``2025-12-23T13:51:50+00:00``.

    Args:
        value: Timestamp string to parse.

    Returns:
        The parsed datetime.

    Raises:
        ValueError: If the string is not a valid ISO-8601 timestamp.
    """
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        msg = f"Invalid ISO-8601 timestamp '{value}'"
        raise ValueError(msg) from exc


def _validate_date_arg(value: str | None, label: str) -> date | None:
    """Parse one date argument, raising a labelled error for malformed values."""
    if value is None:
        return None
    try:
        return parse_strict_date(value)
    except ValueError as exc:
        msg = f"Invalid {label} '{value}': expected YYYY-MM-DD format"
        raise ValueError(msg) from exc


def validate_date_args(
    from_date: str | None,
    to_date: str | None,
) -> tuple[date | None, date | None]:
    """Validate strict ``YYYY-MM-DD`` date arguments and their ordering.

    Args:
        from_date: Start date in ``YYYY-MM-DD`` format, or ``None``.
        to_date: End date in ``YYYY-MM-DD`` format, or ``None``.

    Returns:
        Tuple of parsed ``(from_date, to_date)`` dates; either may be ``None``.

    Raises:
        ValueError: If a date is not exactly ``YYYY-MM-DD``, or ``from_date``
            is after ``to_date``.
    """
    from_parsed = _validate_date_arg(from_date, "from_date")
    to_parsed = _validate_date_arg(to_date, "to_date")
    if from_parsed is not None and to_parsed is not None and from_parsed > to_parsed:
        msg = (
            f"Invalid date range: from_date '{from_date}' must be on or before to_date '{to_date}'"
        )
        raise ValueError(msg)
    return from_parsed, to_parsed


@dataclass(frozen=True, slots=True)
class DateRange:
    """Optional date boundaries for filtering thread exports.

    Groups the from/to date strings into a single value object,
    eliminating the pair of parameters that recurs across scraper,
    cache, and export functions.
    """

    from_date: str | None = None
    to_date: str | None = None


class CacheMetadata(BaseModel):
    """Cache metadata with date coverage information."""

    last_sync_time: datetime = Field(...)
    oldest_thread_date: str | None = Field(default=None)
    newest_thread_date: str | None = Field(default=None)
    total_threads: int = Field(default=0, ge=0)

    @field_validator("last_sync_time")
    @classmethod
    def validate_sync_time(cls, v: datetime) -> datetime:
        """Validate sync time is not in the future."""
        now = datetime.now(v.tzinfo) if v.tzinfo is not None else datetime.now()
        if v > now:
            msg = "last_sync_time cannot be in the future"
            raise ValueError(msg)
        return v

    @field_validator("total_threads")
    @classmethod
    def validate_total_threads(cls, v: int) -> int:
        """Validate total_threads is non-negative."""
        if v < 0:
            msg = "total_threads cannot be negative"
            raise ValueError(msg)
        return v

    @field_validator("oldest_thread_date", "newest_thread_date")
    @classmethod
    def validate_coverage_date(cls, v: str | None) -> str | None:
        """Validate coverage dates are parseable ISO-8601 timestamps."""
        if v is None:
            return v
        parse_iso8601_timestamp(v)
        return v


class CacheFormat(BaseModel):
    """Outer cache file format with encryption metadata."""

    version: int = Field(default=1, ge=1, le=1)
    encrypted: bool = Field(default=True)
    cache: str = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("cache")
    @classmethod
    def validate_cache(cls, v: str) -> str:
        """Validate encrypted cache is not empty."""
        if not v or not v.strip():
            msg = "Encrypted cache cannot be empty"
            raise ValueError(msg)
        return v

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, v: datetime) -> datetime:
        """Validate created_at is not in the future."""
        now = datetime.now(v.tzinfo) if v.tzinfo is not None else datetime.now()
        if v > now:
            msg = "created_at cannot be in the future"
            raise ValueError(msg)
        return v


def _validate_thread_dict(thread: object) -> TypeGuard[dict[str, object]]:
    """Validate that a single thread entry has the required structure.

    Args:
        thread: Item from the threads list to validate.

    Returns:
        True when the thread is a valid dictionary with required fields.

    Raises:
        ValueError: If the thread is not a dict or lacks required fields.
    """
    if not isinstance(thread, dict):
        msg = "Each thread must be a dictionary"
        raise ValueError(msg)
    if "url" not in thread:
        msg = "Each thread must have a 'url' field"
        raise ValueError(msg)
    if "title" not in thread:
        msg = "Each thread must have a 'title' field"
        raise ValueError(msg)
    return True


def _new_threads_list() -> list[dict[str, object]]:
    """Return a new empty list for Field default_factory."""
    return []


class CacheContent(BaseModel):
    """Inner cache content (decrypted)."""

    version: int = Field(default=1, ge=1, le=1)
    metadata: CacheMetadata = Field(...)
    threads: list[dict[str, object]] = Field(default_factory=_new_threads_list)

    @field_validator("threads")
    @classmethod
    def validate_threads(
        cls: type[CacheContent], v: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        """Validate threads list items have required structure."""
        for thread in v:
            _validate_thread_dict(thread)
        return v
