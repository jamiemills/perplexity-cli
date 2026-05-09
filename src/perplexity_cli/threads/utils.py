"""Thread utility functions for data conversion and processing."""

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.utils.exceptions import UpstreamSchemaError


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
    records: list[ThreadRecord] = []
    for thread_dict in thread_dicts:
        if not isinstance(thread_dict, dict):
            raise UpstreamSchemaError("Malformed cached thread record")

        try:
            records.append(
                ThreadRecord(
                    title=thread_dict["title"],
                    url=thread_dict["url"],
                    created_at=thread_dict["created_at"],
                )
            )
        except KeyError as e:
            raise UpstreamSchemaError(f"Malformed cached thread record: missing {e.args[0]}") from e

    return records
