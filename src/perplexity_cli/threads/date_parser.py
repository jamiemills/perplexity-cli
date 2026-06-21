"""Date parsing utilities for thread export functionality.

This module handles parsing and formatting of thread creation timestamps.
"""

from datetime import UTC, datetime, tzinfo

from dateutil import parser as dateutil_parser


def parse_absolute_date_string(date_str: str) -> datetime:
    """Parse absolute date string from Perplexity.ai tooltip to datetime.

    Parses timestamps in the format:
    "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"

    The function handles the "Greenwich Mean Time" suffix by replacing it with
    "UTC" for proper timezone parsing.

    Args:
        date_str: Full timestamp string from tooltip hover text

    Returns:
        datetime object with UTC timezone

    Raises:
        ValueError: If date string cannot be parsed

    Example:
        >>> date_str = "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"
        >>> dt = parse_absolute_date_string(date_str)
        >>> dt.isoformat()
        '2025-12-23T13:51:50+00:00'
    """
    # Replace "Greenwich Mean Time" with "UTC" for dateutil parser
    normalized = date_str.replace("Greenwich Mean Time", "UTC")

    try:
        # Parse the timestamp - dateutil handles the format intelligently
        dt = dateutil_parser.parse(normalized)

        # Ensure we have timezone info (should be UTC from the string)
        if dt.tzinfo is None:
            raise ValueError(f"Parsed datetime has no timezone info: {date_str}")

        return dt
    except (ValueError, TypeError) as e:
        raise ValueError(f"Failed to parse date string '{date_str}': {e}") from e


def to_iso8601(dt: datetime) -> str:
    """Convert datetime to ISO 8601 format with Z suffix.

    Converts a datetime object to ISO 8601 string format with UTC timezone
    represented as 'Z' suffix instead of '+00:00'.

    If the datetime is naive (no timezone), assumes UTC.

    Args:
        dt: datetime object (with or without timezone info)

    Returns:
        ISO 8601 formatted string with Z suffix (e.g., "2025-12-23T13:51:50Z")

    Example:
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2025, 12, 23, 13, 51, 50, tzinfo=timezone.utc)
        >>> to_iso8601(dt)
        '2025-12-23T13:51:50Z'
    """
    # If naive datetime, assume UTC
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=UTC)
    else:
        # Convert to UTC
        utc_dt = dt.astimezone(UTC)

    # Format as ISO 8601 and replace +00:00 with Z
    iso_str = utc_dt.isoformat()
    if iso_str.endswith("+00:00"):
        iso_str = iso_str[:-6] + "Z"

    return iso_str


def _parse_day_start(date_str: str, dt_tzinfo: tzinfo | None) -> datetime:
    """Parse a date string to a datetime at 00:00:00.

    Args:
        date_str: Date string in YYYY-MM-DD format.
        dt_tzinfo: Timezone info to apply to the parsed datetime.

    Returns:
        Datetime at the start of the day.

    Raises:
        ValueError: If date string cannot be parsed.
    """
    return dateutil_parser.parse(date_str).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=dt_tzinfo
    )


def _parse_day_end(date_str: str, dt_tzinfo: tzinfo | None) -> datetime:
    """Parse a date string to a datetime at 23:59:59.999999.

    Args:
        date_str: Date string in YYYY-MM-DD format.
        dt_tzinfo: Timezone info to apply to the parsed datetime.

    Returns:
        Datetime at the end of the day.

    Raises:
        ValueError: If date string cannot be parsed.
    """
    return dateutil_parser.parse(date_str).replace(
        hour=23, minute=59, second=59, microsecond=999999, tzinfo=dt_tzinfo
    )


def _check_after_start(dt: datetime, from_date: str | None) -> bool:
    """Return False if dt is before from_date, True otherwise.

    Args:
        dt: Datetime to check.
        from_date: Lower bound date string, or None for no bound.

    Returns:
        True if dt is on or after from_date (or from_date is None).
    """
    if from_date is None:
        return True
    return dt >= _parse_day_start(from_date, dt.tzinfo)


def _check_before_end(dt: datetime, to_date: str | None) -> bool:
    """Return False if dt is after to_date, True otherwise.

    Args:
        dt: Datetime to check.
        to_date: Upper bound date string, or None for no bound.

    Returns:
        True if dt is on or before to_date (or to_date is None).
    """
    if to_date is None:
        return True
    return dt <= _parse_day_end(to_date, dt.tzinfo)


def is_in_date_range(dt: datetime, from_date: str | None, to_date: str | None) -> bool:
    """Check if datetime falls within specified date range (inclusive).

    Both from_date and to_date are inclusive - threads created ON these dates
    will be included in the results.

    Args:
        dt: datetime to check
        from_date: Start date in YYYY-MM-DD format (inclusive), or None for no lower bound
        to_date: End date in YYYY-MM-DD format (inclusive), or None for no upper bound

    Returns:
        True if datetime is within range, False otherwise

    Raises:
        ValueError: If date strings are not in YYYY-MM-DD format

    Example:
        >>> from datetime import datetime, timezone
        >>> dt = datetime(2025, 12, 23, 13, 51, 50, tzinfo=timezone.utc)
        >>> is_in_date_range(dt, "2025-12-01", "2025-12-31")
        True
        >>> is_in_date_range(dt, "2026-01-01", None)
        False
    """
    try:
        return _check_after_start(dt, from_date) and _check_before_end(dt, to_date)
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid date format. Expected YYYY-MM-DD, got from_date='{from_date}', "
            f"to_date='{to_date}': {e}"
        ) from e
