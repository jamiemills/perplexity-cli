"""CSV export functionality for thread records.

This module handles exporting thread data to CSV format, neutralising
spreadsheet formula prefixes and replacing the destination atomically via a
same-directory temporary file.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from perplexity_cli.utils.atomic_write import atomic_write_text

_FORMULA_PREFIXES = ("=", "+", "-", "@")
_CSV_MODE = 0o644


class ThreadRecord(BaseModel):
    """Data class representing a single thread record.

    Attributes:
        title: Thread question or title text
        url: Full URL to the thread (e.g., https://www.perplexity.ai/search/...)
        created_at: ISO 8601 formatted timestamp with timezone (e.g., 2025-12-23T13:51:50Z)
    """

    title: str
    url: str
    created_at: str


def _neutralise_cell(value: str) -> str:
    """Prefix spreadsheet formula characters with a leading apostrophe."""
    if value.lstrip(" \t\r\n").startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def write_threads_csv(
    records: list[ThreadRecord],
    output_path: Path | None = None,
) -> Path:
    """Write thread records to CSV file.

    Creates a CSV file with columns: created_at, title, url
    Records are written in the order provided (typically newest first). Every
    record cell is checked for spreadsheet formula prefixes (``=``, ``+``,
    ``-``, ``@`` after leading whitespace) and neutralised with an apostrophe.
    The destination is replaced atomically; a pre-existing file is preserved
    byte-for-byte if the write fails.

    Args:
        records: List of ThreadRecord objects to export
        output_path: Optional output file path. If None, generates filename
                    as threads-YYYY-MM-DD-HHMMSS.csv in current directory

    Returns:
        Path to the written CSV file

    Raises:
        IOError: If file cannot be written
        ValueError: If records list is empty

    Example:
        >>> records = [
        ...     ThreadRecord(
        ...         title="Test thread",
        ...         url="https://www.perplexity.ai/search/test-abc123",
        ...         created_at="2025-12-23T13:51:50Z",
        ...     )
        ... ]
        >>> path = write_threads_csv(records)
        >>> print(path)
        threads-2025-12-23-143022.csv
    """
    if not records:
        msg = "Cannot write CSV with empty records list"
        raise ValueError(msg)

    # Generate default filename if not provided
    if output_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        output_path = Path(f"threads-{timestamp}.csv")

    # Ensure path is a Path object
    output_path = Path(output_path)

    # Render the full CSV text before touching the filesystem
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)

    # Write header
    writer.writerow(["created_at", "title", "url"])

    # Write records
    for record in records:
        writer.writerow(
            [
                _neutralise_cell(record.created_at),
                _neutralise_cell(record.title),
                _neutralise_cell(record.url),
            ]
        )

    # Replace the destination atomically
    try:
        atomic_write_text(output_path, buffer.getvalue(), _CSV_MODE)
    except OSError as exc:
        msg = f"Failed to write CSV file to {output_path}: {exc}"
        raise OSError(msg) from exc

    return output_path
