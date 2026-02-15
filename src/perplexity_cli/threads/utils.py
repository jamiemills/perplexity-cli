"""Thread utility functions for data conversion and processing."""

from perplexity_cli.threads.exporter import ThreadRecord


def convert_cache_dicts_to_thread_records(
    thread_dicts: list[dict],
) -> list[ThreadRecord]:
    """Convert cache dictionary entries to ThreadRecord objects.

    Utility function to consolidate the conversion logic used when loading
    threads from cache. Expects dictionaries with 'title', 'url', and
    'created_at' keys.

    Args:
        thread_dicts: List of thread dictionaries from cache.

    Returns:
        List of ThreadRecord objects.
    """
    return [
        ThreadRecord(
            title=t["title"],
            url=t["url"],
            created_at=t["created_at"],
        )
        for t in thread_dicts
    ]
