"""Tests for the thread CSV export functionality."""

import csv
from pathlib import Path

import pytest

from perplexity_cli.threads.exporter import ThreadRecord, write_threads_csv


class TestThreadRecord:
    """Test the ThreadRecord dataclass."""

    def test_creation_with_all_fields(self):
        """Test creating a ThreadRecord with all fields."""
        record = ThreadRecord(
            title="What is Python?",
            url="https://www.perplexity.ai/search/what-is-python-abc123",
            created_at="2025-12-23T13:51:50Z",
        )
        assert record.title == "What is Python?"
        assert record.url == "https://www.perplexity.ai/search/what-is-python-abc123"
        assert record.created_at == "2025-12-23T13:51:50Z"

    def test_creation_with_empty_strings(self):
        """Test creating a ThreadRecord with empty strings."""
        record = ThreadRecord(title="", url="", created_at="")
        assert record.title == ""
        assert record.url == ""
        assert record.created_at == ""

    def test_creation_with_special_characters(self):
        """Test creating a ThreadRecord with special characters in title."""
        record = ThreadRecord(
            title='What are "quotes" & <angles> worth?',
            url="https://www.perplexity.ai/search/special-chars",
            created_at="2025-01-01T00:00:00Z",
        )
        assert record.title == 'What are "quotes" & <angles> worth?'

    def test_creation_with_unicode(self):
        """Test creating a ThreadRecord with Unicode characters."""
        record = ThreadRecord(
            title="Python programming",
            url="https://www.perplexity.ai/search/unicode",
            created_at="2025-01-01T00:00:00Z",
        )
        assert "Python" in record.title


class TestWriteThreadsCsv:
    """Test the write_threads_csv() function."""

    def test_write_single_record(self, tmp_path):
        """Test writing a single record to CSV."""
        output_path = tmp_path / "threads.csv"
        records = [
            ThreadRecord(
                title="What is Python?",
                url="https://www.perplexity.ai/search/python",
                created_at="2025-12-23T13:51:50Z",
            )
        ]

        result_path = write_threads_csv(records, output_path)

        assert result_path == output_path
        assert output_path.exists()

        # Read back and verify content
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 2  # header + 1 record
        assert rows[0] == ["created_at", "title", "url"]
        assert rows[1] == [
            "2025-12-23T13:51:50Z",
            "What is Python?",
            "https://www.perplexity.ai/search/python",
        ]

    def test_write_multiple_records(self, tmp_path):
        """Test writing multiple records to CSV."""
        output_path = tmp_path / "threads.csv"
        records = [
            ThreadRecord(
                title="First thread",
                url="https://www.perplexity.ai/search/first",
                created_at="2025-12-23T14:00:00Z",
            ),
            ThreadRecord(
                title="Second thread",
                url="https://www.perplexity.ai/search/second",
                created_at="2025-12-22T10:00:00Z",
            ),
            ThreadRecord(
                title="Third thread",
                url="https://www.perplexity.ai/search/third",
                created_at="2025-12-21T08:00:00Z",
            ),
        ]

        result_path = write_threads_csv(records, output_path)

        assert result_path == output_path
        assert output_path.exists()

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 4  # header + 3 records
        assert rows[1][1] == "First thread"
        assert rows[2][1] == "Second thread"
        assert rows[3][1] == "Third thread"

    def test_write_empty_records_raises_value_error(self):
        """Test that writing empty records raises ValueError."""
        with pytest.raises(ValueError, match="Cannot write CSV with empty records list"):
            write_threads_csv([])

    def test_write_with_custom_output_path(self, tmp_path):
        """Test writing to a custom output path."""
        custom_path = tmp_path / "custom" / "output" / "my-threads.csv"
        custom_path.parent.mkdir(parents=True, exist_ok=True)

        records = [
            ThreadRecord(
                title="Custom path thread",
                url="https://www.perplexity.ai/search/custom",
                created_at="2025-01-01T00:00:00Z",
            )
        ]

        result_path = write_threads_csv(records, custom_path)

        assert result_path == custom_path
        assert custom_path.exists()

    def test_default_filename_generation(self, tmp_path, monkeypatch):
        """Test that a default filename is generated when no path provided."""
        # Change working directory to tmp_path so the file is created there
        monkeypatch.chdir(tmp_path)

        records = [
            ThreadRecord(
                title="Default filename thread",
                url="https://www.perplexity.ai/search/default",
                created_at="2025-06-15T12:00:00Z",
            )
        ]

        result_path = write_threads_csv(records, output_path=None)

        assert result_path.exists()
        assert result_path.name.startswith("threads-")
        assert result_path.name.endswith(".csv")

    def test_csv_header_order(self, tmp_path):
        """Test that CSV header columns are in the correct order."""
        output_path = tmp_path / "threads.csv"
        records = [
            ThreadRecord(
                title="Header test",
                url="https://example.com",
                created_at="2025-01-01T00:00:00Z",
            )
        ]

        write_threads_csv(records, output_path)

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

        assert header == ["created_at", "title", "url"]

    def test_csv_preserves_special_characters(self, tmp_path):
        """Test that special characters in titles are preserved in CSV."""
        output_path = tmp_path / "threads.csv"
        records = [
            ThreadRecord(
                title='Title with "quotes", commas, and newlines\n in it',
                url="https://example.com/special",
                created_at="2025-01-01T00:00:00Z",
            )
        ]

        write_threads_csv(records, output_path)

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert rows[1][1] == 'Title with "quotes", commas, and newlines\n in it'

    def test_write_returns_path_object(self, tmp_path):
        """Test that write_threads_csv returns a Path object."""
        output_path = tmp_path / "threads.csv"
        records = [
            ThreadRecord(
                title="Path return test",
                url="https://example.com",
                created_at="2025-01-01T00:00:00Z",
            )
        ]

        result = write_threads_csv(records, output_path)
        assert isinstance(result, Path)

    def test_write_utf8_encoding(self, tmp_path):
        """Test that the CSV file is written with UTF-8 encoding."""
        output_path = tmp_path / "threads.csv"
        records = [
            ThreadRecord(
                title="UTF-8 test: cafe, resume, naive",
                url="https://example.com/utf8",
                created_at="2025-01-01T00:00:00Z",
            )
        ]

        write_threads_csv(records, output_path)

        # Verify we can read it back as UTF-8
        content = output_path.read_text(encoding="utf-8")
        assert "UTF-8 test" in content
