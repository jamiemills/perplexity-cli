"""Thread context storage and management for follow-up queries."""

import json
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from perplexity_cli.api.models import ThreadContext
from perplexity_cli.utils.config import get_config_dir
from perplexity_cli.utils.logging import get_logger

# Cache TTL: 30 days
CACHE_TTL_DAYS = 30


def get_threads_cache_path() -> Path:
    """Get the path to the threads cache file.

    Returns:
        Path: Path to ~/.config/perplexity-cli/threads.json (or platform equivalent).
    """
    return get_config_dir() / "threads.json"


def save_thread_context(thread_slug: str, context: ThreadContext) -> None:
    """Save thread context to cache file.

    Stores thread context with timestamp for cache management.
    Creates the cache file if it doesn't exist.

    Args:
        thread_slug: The thread slug identifier.
        context: The ThreadContext object to save.

    Raises:
        IOError: If the cache file cannot be written.
    """
    logger = get_logger()
    cache_path = get_threads_cache_path()

    try:
        # Load existing cache or create new dict
        cache_data: dict[str, Any] = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r") as f:
                    cache_data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not read existing cache file: {e}, creating new one")
                cache_data = {}

        # Update cache with new context
        cache_data[thread_slug] = {
            "context": context.to_dict(),
            "saved_at": datetime.now().isoformat(),
        }

        # Write cache back to file
        with open(cache_path, "w") as f:
            json.dump(cache_data, f, indent=2)

        # Set restrictive permissions (0600)
        os.chmod(cache_path, 0o600)

        logger.debug(f"Saved thread context for slug: {thread_slug}")

    except OSError as e:
        logger.error(f"Failed to save thread context: {e}", exc_info=True)
        raise IOError(f"Failed to save thread context to {cache_path}: {e}") from e


def load_thread_context(thread_slug: str) -> ThreadContext | None:
    """Load thread context from cache file.

    Checks TTL and returns None if context is expired or not found.

    Args:
        thread_slug: The thread slug identifier.

    Returns:
        ThreadContext if found and not expired, None otherwise.
    """
    logger = get_logger()
    cache_path = get_threads_cache_path()

    if not cache_path.exists():
        logger.debug(f"Cache file does not exist: {cache_path}")
        return None

    try:
        with open(cache_path, "r") as f:
            cache_data = json.load(f)

        if thread_slug not in cache_data:
            logger.debug(f"Thread slug not found in cache: {thread_slug}")
            return None

        thread_data = cache_data[thread_slug]
        saved_at_str = thread_data.get("saved_at")
        context_dict = thread_data.get("context")

        if not context_dict:
            logger.warning(f"Invalid cache entry for slug: {thread_slug}")
            return None

        # Check TTL
        if saved_at_str:
            try:
                saved_at = datetime.fromisoformat(saved_at_str)
                age = datetime.now() - saved_at
                if age > timedelta(days=CACHE_TTL_DAYS):
                    logger.debug(
                        f"Thread context expired (age: {age.days} days > {CACHE_TTL_DAYS} days)"
                    )
                    return None
            except (ValueError, TypeError) as e:
                logger.warning(f"Could not parse saved_at timestamp: {e}")

        # Create ThreadContext from dict
        return ThreadContext.from_dict(context_dict)

    except (json.JSONDecodeError, IOError, KeyError) as e:
        logger.warning(f"Could not load thread context: {e}")
        return None


def clear_thread_context(thread_slug: str | None = None) -> None:
    """Clear thread context from cache.

    If thread_slug is provided, clears only that thread's context.
    If thread_slug is None, clears all cached contexts.

    Args:
        thread_slug: Optional thread slug to clear. If None, clears all.
    """
    logger = get_logger()
    cache_path = get_threads_cache_path()

    if not cache_path.exists():
        logger.debug("Cache file does not exist, nothing to clear")
        return

    try:
        with open(cache_path, "r") as f:
            cache_data = json.load(f)

        if thread_slug:
            if thread_slug in cache_data:
                del cache_data[thread_slug]
                logger.debug(f"Cleared thread context for slug: {thread_slug}")
            else:
                logger.debug(f"Thread slug not found in cache: {thread_slug}")
        else:
            cache_data.clear()
            logger.debug("Cleared all thread contexts")

        # Write updated cache back to file
        with open(cache_path, "w") as f:
            json.dump(cache_data, f, indent=2)

        # Set restrictive permissions (0600)
        os.chmod(cache_path, 0o600)

    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to clear thread context: {e}", exc_info=True)
        raise IOError(f"Failed to clear thread context from {cache_path}: {e}") from e

