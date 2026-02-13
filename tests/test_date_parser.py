"""Tests for the date parser module used in thread export."""

from datetime import UTC, datetime, timezone

import pytest

from perplexity_cli.threads.date_parser import (
    is_in_date_range,
    parse_absolute_date_string,
    to_iso8601,
)


class TestParseAbsoluteDateString:
    """Test parse_absolute_date_string() function."""

    def test_parse_standard_perplexity_timestamp(self):
        """Test parsing a standard Perplexity.ai tooltip timestamp."""
        date_str = "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"
        result = parse_absolute_date_string(date_str)

        assert result.year == 2025
        assert result.month == 12
        assert result.day == 23
        assert result.hour == 13
        assert result.minute == 51
        assert result.second == 50
        assert result.tzinfo is not None

    def test_parse_morning_timestamp(self):
        """Test parsing a morning timestamp with AM."""
        date_str = "Monday, January 6, 2025 at 9:05:30 AM Greenwich Mean Time"
        result = parse_absolute_date_string(date_str)

        assert result.year == 2025
        assert result.month == 1
        assert result.day == 6
        assert result.hour == 9
        assert result.minute == 5
        assert result.second == 30

    def test_parse_midnight_timestamp(self):
        """Test parsing a midnight timestamp."""
        date_str = "Wednesday, March 5, 2025 at 12:00:00 AM Greenwich Mean Time"
        result = parse_absolute_date_string(date_str)

        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0

    def test_parse_noon_timestamp(self):
        """Test parsing a noon timestamp."""
        date_str = "Wednesday, March 5, 2025 at 12:00:00 PM Greenwich Mean Time"
        result = parse_absolute_date_string(date_str)

        assert result.hour == 12

    def test_result_has_timezone_info(self):
        """Test that parsed datetime has timezone information."""
        date_str = "Friday, February 14, 2025 at 3:30:00 PM Greenwich Mean Time"
        result = parse_absolute_date_string(date_str)

        assert result.tzinfo is not None

    def test_invalid_date_string_raises_value_error(self):
        """Test that an unparseable date string raises ValueError."""
        with pytest.raises(ValueError, match="Failed to parse date string"):
            parse_absolute_date_string("not a date at all")

    def test_empty_string_raises_value_error(self):
        """Test that an empty string raises ValueError."""
        with pytest.raises(ValueError):
            parse_absolute_date_string("")


class TestToIso8601:
    """Test to_iso8601() function."""

    def test_utc_datetime(self):
        """Test conversion of UTC-aware datetime."""
        dt = datetime(2025, 12, 23, 13, 51, 50, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2025-12-23T13:51:50Z"

    def test_naive_datetime_assumes_utc(self):
        """Test that naive datetime is assumed to be UTC."""
        dt = datetime(2025, 6, 15, 10, 30, 0)
        result = to_iso8601(dt)
        assert result == "2025-06-15T10:30:00Z"

    def test_midnight_datetime(self):
        """Test conversion of midnight datetime."""
        dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2025-01-01T00:00:00Z"

    def test_end_of_day_datetime(self):
        """Test conversion of end-of-day datetime."""
        dt = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2025-12-31T23:59:59Z"

    def test_datetime_with_microseconds(self):
        """Test that microseconds are included in output."""
        dt = datetime(2025, 3, 15, 12, 0, 0, 123456, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2025-03-15T12:00:00.123456Z"

    def test_different_timezone_converted_to_utc(self):
        """Test that a non-UTC timezone is converted to UTC."""
        # Create a datetime at UTC+5
        from datetime import timedelta

        tz_plus5 = timezone(timedelta(hours=5))
        dt = datetime(2025, 7, 20, 15, 0, 0, tzinfo=tz_plus5)
        result = to_iso8601(dt)
        # 15:00 UTC+5 = 10:00 UTC
        assert result == "2025-07-20T10:00:00Z"

    def test_result_ends_with_z(self):
        """Test that the result always ends with Z."""
        dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result.endswith("Z")

    def test_result_is_valid_iso_format(self):
        """Test that the result is valid ISO 8601 format (parseable)."""
        dt = datetime(2025, 8, 10, 14, 30, 45, tzinfo=UTC)
        result = to_iso8601(dt)
        # Should be parseable back (strip the Z and add +00:00 for fromisoformat)
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert parsed.year == 2025
        assert parsed.month == 8
        assert parsed.day == 10


class TestIsInDateRange:
    """Test is_in_date_range() function."""

    def test_both_dates_none_returns_true(self):
        """Test that no filtering returns True for any datetime."""
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert is_in_date_range(dt, None, None) is True

    def test_within_range(self):
        """Test datetime within the specified range."""
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-01", "2025-06-30") is True

    def test_before_from_date(self):
        """Test datetime before from_date returns False."""
        dt = datetime(2025, 5, 31, 23, 59, 59, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-01", "2025-06-30") is False

    def test_after_to_date(self):
        """Test datetime after to_date returns False."""
        dt = datetime(2025, 7, 1, 0, 0, 1, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-01", "2025-06-30") is False

    def test_on_from_date_boundary_inclusive(self):
        """Test datetime exactly on from_date is included (inclusive)."""
        dt = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-01", "2025-06-30") is True

    def test_on_to_date_boundary_inclusive(self):
        """Test datetime on to_date at end of day is included (inclusive)."""
        dt = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-01", "2025-06-30") is True

    def test_from_date_only(self):
        """Test filtering with only from_date (no upper bound)."""
        dt = datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-01-01", None) is True

    def test_from_date_only_before(self):
        """Test datetime before from_date with no upper bound."""
        dt = datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-01-01", None) is False

    def test_to_date_only(self):
        """Test filtering with only to_date (no lower bound)."""
        dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert is_in_date_range(dt, None, "2025-12-31") is True

    def test_to_date_only_after(self):
        """Test datetime after to_date with no lower bound."""
        dt = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
        assert is_in_date_range(dt, None, "2025-12-31") is False

    def test_same_from_and_to_date(self):
        """Test with from_date equal to to_date."""
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-15", "2025-06-15") is True

    def test_same_from_and_to_date_different_day(self):
        """Test datetime on a different day when from_date equals to_date."""
        dt = datetime(2025, 6, 14, 12, 0, 0, tzinfo=UTC)
        assert is_in_date_range(dt, "2025-06-15", "2025-06-15") is False

    def test_invalid_from_date_format_raises(self):
        """Test that an invalid from_date format raises ValueError."""
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Invalid date format"):
            is_in_date_range(dt, "not-a-date", "2025-06-30")

    def test_invalid_to_date_format_raises(self):
        """Test that an invalid to_date format raises ValueError."""
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="Invalid date format"):
            is_in_date_range(dt, "2025-06-01", "not-a-date")
