"""Thread cache management with encryption and smart invalidation.

This module provides local encrypted caching of thread data to reduce API calls.
Threads are cached with metadata tracking oldest/newest dates for smart
invalidation - only fetching fresh data when necessary.
"""

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.models import CacheContent, CacheFormat
from perplexity_cli.utils.config import get_config_paths
from perplexity_cli.utils.encryption import decrypt_token, encrypt_token
from perplexity_cli.utils.exceptions import ConfigurationError
from perplexity_cli.utils.file_permissions import verify_secure_permissions
from perplexity_cli.utils.logging import get_logger, redact_path


class ThreadCacheManager:
    """Manage local encrypted thread cache with smart invalidation.

    Stores threads in an encrypted JSON file with metadata tracking date coverage.
    Implements smart cache validation - only fetches fresh data if requested date
    range extends beyond cached data.

    Cache File Format:
        ~/.config/perplexity-cli/threads-cache.json (encrypted)

    Encryption:
        Uses same deterministic system-derived key as auth token (hostname + OS user).
        Machine-specific: cannot decrypt on different machine.
        This is machine-bound obfuscation, not OS-backed secret storage.
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
            cache_path = get_config_paths().cache_path

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
            with open(self.cache_path, encoding="utf-8") as f:
                raw_data = json.load(f)

            validated_cache = self._validate_outer_format(raw_data)
            cache_data = self._decrypt_and_validate_cache(validated_cache)

            # Audit log: cache loaded
            self.logger.info("Cache loaded from %s", redact_path(self.cache_path))
            return cache_data.model_dump(mode="json")

        except (OSError, json.JSONDecodeError) as e:
            self.logger.error("Failed to load cache: %s", e, exc_info=True)
            raise OSError(f"Failed to load cache from {self.cache_path}: {e}") from e

    def _validate_outer_format(self, raw_data: dict) -> CacheFormat:
        """Validate and parse the outer cache file format.

        Args:
            raw_data: Raw JSON data from cache file.

        Returns:
            Validated CacheFormat instance.

        Raises:
            ConfigurationError: If format is invalid or cache is not encrypted.
        """
        try:
            cache_format = CacheFormat.model_validate(raw_data)
        except ValidationError as e:
            self.logger.error("Cache file has invalid outer format: %s", e)
            raise ConfigurationError("Cache file has invalid format") from e

        if not cache_format.encrypted:
            self.logger.warning("Cache file is not encrypted")
            raise ConfigurationError(
                "Cache file is not encrypted. Cache may be corrupted. "
                "Consider deleting and rebuilding."
            )

        if not cache_format.cache:
            self.logger.error("Cache file missing encrypted cache data")
            raise ConfigurationError("Cache file is missing encrypted cache data")

        return cache_format

    def _decrypt_and_validate_cache(  # nosemgrep: meaningless-name
        self, data: CacheFormat
    ) -> CacheContent:
        """Decrypt and validate the inner cache content.

        Args:
            data: Validated outer cache format containing encrypted payload.

        Returns:
            Validated CacheContent instance.

        Raises:
            ConfigurationError: If decrypted content has invalid format.
        """
        decrypted_json = decrypt_token(data.cache)
        decrypted_data = json.loads(decrypted_json)

        try:
            return CacheContent.model_validate(decrypted_data)
        except ValidationError as e:
            self.logger.error("Cache content has invalid format: %s", e)
            raise ConfigurationError("Cache content has invalid format") from e

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
            with open(self.cache_path, "w", encoding="utf-8") as f:
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
            self.logger.info(
                "Cache saved to %s (%s threads)", redact_path(self.cache_path), len(threads)
            )

        except OSError as e:
            self.logger.error("Failed to save cache: %s", e, exc_info=True)
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
        except (ConfigurationError, OSError):
            # Cache load failed, consider no coverage
            return None, None

    def _parse_cache_coverage(self) -> tuple[date, date] | None:
        """Parse the date coverage from the current cache.

        Returns:
            Tuple of (oldest_date, newest_date) as date objects, or None
            if cache does not exist or metadata is incomplete.
        """
        from dateutil import parser as dateutil_parser

        cache = self.load_cache()
        if not cache:
            return None

        metadata = cache.get("metadata", {})
        cache_oldest_str = metadata.get("oldest_thread_date")
        cache_newest_str = metadata.get("newest_thread_date")

        if not cache_oldest_str or not cache_newest_str:
            return None

        return (
            dateutil_parser.parse(cache_oldest_str).date(),
            dateutil_parser.parse(cache_newest_str).date(),
        )

    @staticmethod
    def _calculate_fetch_range(
        request_from: date, request_to: date, cache_oldest: date, cache_newest: date
    ) -> tuple[bool, str | None, str | None]:
        """Calculate the date range that needs fetching from the API.

        Args:
            request_from: Requested start date.
            request_to: Requested end date.
            cache_oldest: Oldest date in cache.
            cache_newest: Newest date in cache.

        Returns:
            Tuple of (needs_fetch, fetch_from_iso, fetch_to_iso).
        """
        needs_older = request_from < cache_oldest
        needs_newer = request_to >= cache_newest

        if not (needs_older or needs_newer):
            return False, None, None

        fetch_from = request_from if needs_older else cache_newest
        return True, fetch_from.isoformat(), request_to.isoformat()

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

        coverage = self._parse_cache_coverage()
        if coverage is None:
            return True, from_date, to_date

        cache_oldest, cache_newest = coverage
        request_from = dateutil_parser.parse(from_date).date() if from_date else cache_oldest
        request_to = dateutil_parser.parse(to_date).date() if to_date else datetime.now(UTC).date()

        return self._calculate_fetch_range(request_from, request_to, cache_oldest, cache_newest)

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
            self.logger.debug("Deduplicated %s duplicate threads", deduped_count)

        return merged

    def clear_cache(self) -> None:
        """Delete cache file from disk.

        Silently succeeds if cache does not exist.
        """
        if self.cache_path.exists():
            try:
                self.cache_path.unlink()
                # Audit log: cache cleared
                self.logger.info("Cache cleared from %s", self.cache_path)
            except OSError as e:
                self.logger.error("Failed to delete cache file: %s", e, exc_info=True)
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
        verify_secure_permissions(
            self.cache_path,
            expected_permissions=self.SECURE_PERMISSIONS,
            file_type="cache",
            logger=self.logger,
        )
