"""Thread cache management with encryption and smart invalidation.

This module provides local encrypted caching of thread data to reduce API calls.
Threads are cached with metadata tracking oldest/newest dates for smart
invalidation - only fetching fresh data when necessary.
"""

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.utils.config import get_config_dir
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
from perplexity_cli.utils.logging import get_logger


class ThreadCacheManager:
    """Manage local encrypted thread cache with smart invalidation.

    Stores threads in an encrypted JSON file with metadata tracking date coverage.
    Implements smart cache validation - only fetches fresh data if requested date
    range extends beyond cached data.

    Cache File Format:
        ~/.config/perplexity-cli/threads-cache.json (encrypted)

    Encryption:
        Uses same system-derived key as auth token (hostname + OS user).
        Machine-specific: cannot decrypt on different machine.
        File permissions: 0600 (owner read/write only)
    """

    # File permissions: owner read/write only (0600)
    SECURE_PERMISSIONS = 0o600

    # Cache metadata version for schema migrations
    CACHE_VERSION = 1

    def __init__(self, cache_path: Path | None = None) -> None:
        """Initialise cache manager.

        Args:
            cache_path: Path to cache file. Defaults to
                ~/.config/perplexity-cli/threads-cache.json
        """
        if cache_path is None:
            cache_path = get_config_dir() / "threads-cache.json"

        self.cache_path = cache_path
        self.logger = get_logger()

    def load_cache(self) -> dict[str, Any] | None:
        """Load and decrypt cache from disk.

        Returns:
            Cache dictionary containing:
                - version: Cache schema version
                - encrypted: Always True
                - metadata: Dict with last_sync_time, oldest_thread_date, etc.
                - threads: List of ThreadRecord dicts
            Or None if cache doesn't exist.

        Raises:
            RuntimeError: If cache exists but decryption fails or cache corrupted.
            IOError: If cache file cannot be read.
        """
        if not self.cache_path.exists():
            return None

        # Verify file permissions
        self._verify_permissions()

        try:
            with open(self.cache_path) as f:
                data = json.load(f)

            # Check if cache is encrypted
            if not data.get("encrypted", False):
                self.logger.warning("Cache file is not encrypted")
                raise RuntimeError(
                    "Cache file is not encrypted. Cache may be corrupted. "
                    "Consider deleting and rebuilding."
                )

            encrypted_cache = data.get("cache")
            if not encrypted_cache:
                self.logger.error("Cache file missing encrypted cache data")
                raise RuntimeError("Cache file is missing encrypted cache data")

            # Decrypt the cache
            decrypted_json = decrypt_token(encrypted_cache)
            cache_data = json.loads(decrypted_json)

            # Audit log: cache loaded
            self.logger.info(f"Cache loaded from {self.cache_path}")

            return cache_data

        except (OSError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load cache: {e}", exc_info=True)
            raise OSError(f"Failed to load cache from {self.cache_path}: {e}") from e

    def save_cache(
        self,
        threads: list[ThreadRecord],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Encrypt and save cache to disk.

        Args:
            threads: List of ThreadRecord objects to cache.
            metadata: Optional metadata dict. If None, auto-generates with current time.

        Raises:
            IOError: If cache cannot be written or permissions cannot be set.
            RuntimeError: If encryption fails.
        """
        try:
            # Build metadata if not provided
            if metadata is None:
                metadata = self._build_cache_metadata(threads)

            # Convert ThreadRecords to dicts for serialisation
            threads_dicts = [
                {
                    "title": t.title,
                    "url": t.url,
                    "created_at": t.created_at,
                }
                for t in threads
            ]

            # Build cache structure
            cache_data = {
                "version": self.CACHE_VERSION,
                "metadata": metadata,
                "threads": threads_dicts,
            }

            # Serialise to JSON and encrypt
            cache_json = json.dumps(cache_data)
            encrypted_cache = encrypt_token(cache_json)

            # Write encrypted cache to file with metadata
            with open(self.cache_path, "w") as f:
                json.dump(
                    {
                        "version": self.CACHE_VERSION,
                        "encrypted": True,
                        "cache": encrypted_cache,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                    f,
                )

            # Set restrictive permissions
            os.chmod(self.cache_path, self.SECURE_PERMISSIONS)

            # Audit log: cache saved
            self.logger.info(f"Cache saved to {self.cache_path} ({len(threads)} threads)")

        except OSError as e:
            self.logger.error(f"Failed to save cache: {e}", exc_info=True)
            raise OSError(
                f"Failed to save or set permissions on cache file {self.cache_path}: {e}"
            ) from e

    def get_cache_coverage(self) -> tuple[str | None, str | None]:
        """Get date range covered by cache.

        Returns:
            Tuple of (oldest_date_iso8601, newest_date_iso8601).
            Returns (None, None) if cache doesn't exist or is empty.
        """
        try:
            cache = self.load_cache()
            if not cache:
                return None, None

            metadata = cache.get("metadata", {})
            oldest = metadata.get("oldest_thread_date")
            newest = metadata.get("newest_thread_date")

            return oldest, newest
        except (RuntimeError, OSError):
            # Cache load failed, consider no coverage
            return None, None

    def requires_fresh_data(
        self,
        from_date: str | None,
        to_date: str | None,
    ) -> tuple[bool, str | None, str | None]:
        """Determine if cache requires fresh data for requested date range.

        Implements smart invalidation: only fetches if requested dates extend
        beyond cache coverage. Always includes cache_newest_date in fetch range
        to catch any additional threads added on that same day.

        Args:
            from_date: Requested start date (YYYY-MM-DD format) or None.
            to_date: Requested end date (YYYY-MM-DD format) or None.

        Returns:
            Tuple of (needs_fresh_data: bool, fetch_from_date: str | None, fetch_to_date: str | None)
            - needs_fresh_data: True if API fetch needed, False if cache sufficient
            - fetch_from_date: Start date for API fetch (if needed), or None
            - fetch_to_date: End date for API fetch (if needed), or None

        Raises:
            ValueError: If date format is invalid.
        """
        from dateutil import parser as dateutil_parser

        cache = self.load_cache()

        # No cache exists - need to fetch everything
        if not cache:
            return True, from_date, to_date

        metadata = cache.get("metadata", {})
        cache_oldest_str = metadata.get("oldest_thread_date")
        cache_newest_str = metadata.get("newest_thread_date")

        if not cache_oldest_str or not cache_newest_str:
            # Cache metadata incomplete
            return True, from_date, to_date

        # Parse cache coverage dates
        cache_oldest = dateutil_parser.parse(cache_oldest_str).date()
        cache_newest = dateutil_parser.parse(cache_newest_str).date()

        # Parse request dates (use today if to_date not specified)
        request_from = dateutil_parser.parse(from_date).date() if from_date else cache_oldest
        request_to = dateutil_parser.parse(to_date).date() if to_date else datetime.now(UTC).date()

        # Determine if gaps exist in cache coverage
        needs_older = request_from < cache_oldest
        needs_newer = request_to >= cache_newest  # Include cache_newest_date

        if not (needs_older or needs_newer):
            # Cache covers entire requested range
            return False, None, None

        # Calculate fetch dates (cover the gaps)
        fetch_from = request_from if needs_older else cache_newest
        fetch_to = request_to

        # Convert back to ISO date strings
        fetch_from_str = fetch_from.isoformat()
        fetch_to_str = fetch_to.isoformat()

        return True, fetch_from_str, fetch_to_str

    def merge_threads(
        self,
        cached_threads: list[ThreadRecord],
        new_threads: list[ThreadRecord],
    ) -> list[ThreadRecord]:
        """Merge cached threads with newly fetched threads.

        - Eliminates duplicates by URL (keeps cached version, never replaces)
        - Returns combined list sorted by created_at (newest first)
        - Guarantees: never overwrites cached threads with new data

        Args:
            cached_threads: Threads from cache.
            new_threads: Threads from API.

        Returns:
            Merged list of unique threads, sorted newest-first.
        """
        # Build set of cached URLs (to prevent replacement)
        cached_urls = {t.url for t in cached_threads}

        # Add only new threads (not already in cache)
        merged = list(cached_threads)
        for thread in new_threads:
            if thread.url not in cached_urls:
                merged.append(thread)
                cached_urls.add(thread.url)

        # Sort by created_at (newest first)
        merged.sort(
            key=lambda t: t.created_at,
            reverse=True,
        )

        deduped_count = len(new_threads) - (len(merged) - len(cached_threads))
        if deduped_count > 0:
            self.logger.debug(f"Deduplicated {deduped_count} duplicate threads")

        return merged

    def clear_cache(self) -> None:
        """Delete cache file from disk.

        Silently succeeds if cache does not exist.
        """
        if self.cache_path.exists():
            try:
                self.cache_path.unlink()
                # Audit log: cache cleared
                self.logger.info(f"Cache cleared from {self.cache_path}")
            except OSError as e:
                self.logger.error(f"Failed to delete cache file: {e}", exc_info=True)
                raise OSError(f"Failed to delete cache file: {e}") from e

    def cache_exists(self) -> bool:
        """Check if cache file exists on disk.

        Returns:
            True if cache file exists, False otherwise.
        """
        return self.cache_path.exists()

    def _build_cache_metadata(self, threads: list[ThreadRecord]) -> dict[str, Any]:
        """Build cache metadata from thread list.

        Args:
            threads: List of ThreadRecord objects.

        Returns:
            Metadata dictionary with timestamps and date coverage.
        """
        if not threads:
            return {
                "last_sync_time": datetime.now(UTC).isoformat(),
                "oldest_thread_date": None,
                "newest_thread_date": None,
                "total_threads": 0,
            }

        # Threads are expected to be sorted newest-first
        oldest = threads[-1].created_at
        newest = threads[0].created_at

        return {
            "last_sync_time": datetime.now(UTC).isoformat(),
            "oldest_thread_date": oldest,
            "newest_thread_date": newest,
            "total_threads": len(threads),
        }

    def _verify_permissions(self) -> None:
        """Verify that cache file has secure permissions (0600).

        Raises:
            RuntimeError: If file permissions are not 0600.
        """
        file_stat = self.cache_path.stat()
        actual_permissions = stat.S_IMODE(file_stat.st_mode)

        if actual_permissions != self.SECURE_PERMISSIONS:
            self.logger.error(
                f"Cache file has insecure permissions: {oct(actual_permissions)} "
                f"(expected {oct(self.SECURE_PERMISSIONS)})"
            )
            raise RuntimeError(
                f"Cache file has insecure permissions: {oct(actual_permissions)}. "
                f"Expected {oct(self.SECURE_PERMISSIONS)}. "
                f"Cache file may have been compromised."
            )
