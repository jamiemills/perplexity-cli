"""CSV export functionality for thread records.

This module handles exporting thread data to CSV format.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ThreadRecord:
    """Data class representing a single thread record.

    Attributes:
        title: Thread question or title text
        url: Full URL to the thread (e.g., https://www.perplexity.ai/search/...)
        created_at: ISO 8601 formatted timestamp with timezone (e.g., 2025-12-23T13:51:50Z)
    """

    title: str
    url: str
    created_at: str


def write_threads_csv(
    records: list[ThreadRecord],
    output_path: Path | None = None,
) -> Path:
    """Write thread records to CSV file.

    Creates a CSV file with columns: created_at, title, url
    Records are written in the order provided (typically newest first).

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
        ...         created_at="2025-12-23T13:51:50Z"
        ...     )
        ... ]
        >>> path = write_threads_csv(records)
        >>> print(path)
        threads-2025-12-23-143022.csv
    """
    if not records:
        raise ValueError("Cannot write CSV with empty records list")

    # Generate default filename if not provided
    if output_path is None:
        timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        output_path = Path(f"threads-{timestamp}.csv")

    # Ensure path is a Path object
    output_path = Path(output_path)

    # Write CSV file
    try:
        with output_path.open("w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            # Write header
            writer.writerow(["created_at", "title", "url"])

            # Write records
            for record in records:
                writer.writerow([record.created_at, record.title, record.url])

        return output_path
    except OSError as e:
        raise OSError(f"Failed to write CSV file to {output_path}: {e}") from e
