"""Date parsing utilities for thread export functionality.

This module handles parsing and formatting of thread creation timestamps.
"""

from datetime import UTC, datetime

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
    # No filtering if both dates are None
    if from_date is None and to_date is None:
        return True

    # Parse date strings to datetime objects at start/end of day
    try:
        if from_date is not None:
            # Start of day (00:00:00)
            from_dt = dateutil_parser.parse(from_date).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=dt.tzinfo
            )
            if dt < from_dt:
                return False

        if to_date is not None:
            # End of day (23:59:59)
            to_dt = dateutil_parser.parse(to_date).replace(
                hour=23, minute=59, second=59, microsecond=999999, tzinfo=dt.tzinfo
            )
            if dt > to_dt:
                return False

        return True
    except (ValueError, TypeError) as e:
        raise ValueError(
            f"Invalid date format. Expected YYYY-MM-DD, got from_date='{from_date}', "
            f"to_date='{to_date}': {e}"
        ) from e
