"""Tests for thread caching functionality.

Tests the ThreadCacheManager class, cache invalidation logic, and encryption.
"""

import json
import os
import stat

import pytest

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.utils import convert_cache_dicts_to_thread_records
from perplexity_cli.utils.exceptions import ConfigurationError, UpstreamSchemaError


class TestThreadCacheManager:
    """Test ThreadCacheManager encryption and storage."""

    @pytest.fixture
    def sample_threads(self):
        """Provide sample ThreadRecord objects for testing."""
        return [
            ThreadRecord(
                title="Thread 1",
                url="https://example.com/1",
                created_at="2025-12-23T13:51:50Z",
            ),
            ThreadRecord(
                title="Thread 2",
                url="https://example.com/2",
                created_at="2025-12-22T10:30:00Z",
            ),
            ThreadRecord(
                title="Thread 3",
                url="https://example.com/3",
                created_at="2025-12-21T08:15:00Z",
            ),
        ]

    def test_cache_does_not_exist_initially(self, cache_manager):
        """Test that cache doesn't exist before creation."""
        assert not cache_manager.cache_exists()
        assert cache_manager.load_cache() is None

    def test_save_and_load_cache(self, cache_manager, sample_threads):
        """Test saving and loading encrypted cache."""
        # Save cache
        cache_manager.save_cache(sample_threads)
        assert cache_manager.cache_exists()

        # Load cache
        loaded = cache_manager.load_cache()
        assert loaded is not None
        assert len(loaded["threads"]) == 3
        assert loaded["threads"][0]["title"] == "Thread 1"

    def test_cache_file_permissions(self, cache_manager, sample_threads):
        """Test that cache file has secure permissions (0600)."""
        cache_manager.save_cache(sample_threads)

        file_stat = cache_manager.cache_path.stat()
        permissions = stat.S_IMODE(file_stat.st_mode)
        assert permissions == 0o600, f"Expected 0600, got {oct(permissions)}"

    def test_cache_is_encrypted(self, cache_manager, sample_threads):
        """Test that cache file contains encrypted data."""
        cache_manager.save_cache(sample_threads)

        # Read raw file content
        with open(cache_manager.cache_path, encoding="utf-8") as f:
            content = json.load(f)

        # Should have encryption wrapper
        assert content.get("encrypted") is True
        assert "cache" in content

        # Encrypted data should not be plain JSON
        encrypted_data = content["cache"]
        assert not encrypted_data.startswith("[")
        assert not encrypted_data.startswith("{")

    def test_cache_metadata_tracking(self, cache_manager, sample_threads):
        """Test that cache metadata tracks date coverage."""
        cache_manager.save_cache(sample_threads)
        loaded = cache_manager.load_cache()

        metadata = loaded["metadata"]
        assert metadata["oldest_thread_date"] == "2025-12-21T08:15:00Z"
        assert metadata["newest_thread_date"] == "2025-12-23T13:51:50Z"
        assert metadata["total_threads"] == 3

    def test_cache_metadata_derives_coverage_from_actual_min_max(self, cache_manager):
        """Coverage must be derived from actual min/max timestamps, not caller order."""
        unsorted_threads = [
            ThreadRecord(
                title="Middle",
                url="https://example.com/middle",
                created_at="2025-12-22T10:00:00Z",
            ),
            ThreadRecord(
                title="Newest",
                url="https://example.com/newest",
                created_at="2025-12-23T13:51:50Z",
            ),
            ThreadRecord(
                title="Oldest",
                url="https://example.com/oldest",
                created_at="2025-12-21T08:15:00Z",
            ),
        ]
        cache_manager.save_cache(unsorted_threads)
        loaded = cache_manager.load_cache()

        metadata = loaded["metadata"]
        assert metadata["oldest_thread_date"] == "2025-12-21T08:15:00Z"
        assert metadata["newest_thread_date"] == "2025-12-23T13:51:50Z"
        assert metadata["total_threads"] == 3

    def test_save_cache_is_atomic_and_leaves_no_temp_files(self, cache_manager, sample_threads):
        """save_cache writes atomically and leaves no temporary siblings."""
        cache_manager.save_cache(sample_threads)
        cache_manager.save_cache(sample_threads[:1])

        siblings = list(cache_manager.cache_path.parent.glob(f".{cache_manager.cache_path.name}.*"))
        assert siblings == []

        loaded = cache_manager.load_cache()
        assert len(loaded["threads"]) == 1

    def test_get_cache_coverage(self, cache_manager, sample_threads):
        """Test get_cache_coverage returns correct date range."""
        cache_manager.save_cache(sample_threads)

        oldest, newest = cache_manager.get_cache_coverage()
        assert oldest == "2025-12-21T08:15:00Z"
        assert newest == "2025-12-23T13:51:50Z"

    def test_get_cache_coverage_empty(self, cache_manager):
        """Test get_cache_coverage returns None when cache doesn't exist."""
        oldest, newest = cache_manager.get_cache_coverage()
        assert oldest is None
        assert newest is None

    def test_clear_cache(self, cache_manager, sample_threads):
        """Test clearing cache file."""
        cache_manager.save_cache(sample_threads)
        assert cache_manager.cache_exists()

        cache_manager.clear_cache()
        assert not cache_manager.cache_exists()

    def test_clear_cache_nonexistent(self, cache_manager):
        """Test clearing cache when it doesn't exist (should not error)."""
        # Should not raise
        cache_manager.clear_cache()
        assert not cache_manager.cache_exists()

    def test_load_cache_rejects_invalid_outer_format(self, cache_manager):
        """Test invalid outer cache format fails predictably."""
        cache_manager.cache_path.write_text(
            json.dumps({"version": 1, "encrypted": True, "cache": "   "}),
            encoding="utf-8",
        )
        os.chmod(cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS)

        with pytest.raises(ConfigurationError, match="Cache file has invalid format"):
            cache_manager.load_cache()

    def test_load_cache_rejects_invalid_inner_format(self, cache_manager):
        """Test invalid decrypted cache payload fails predictably."""
        from perplexity_cli.utils.encryption import encrypt_token

        invalid_inner_cache = {
            "version": 1,
            "metadata": {
                "last_sync_time": "2025-12-23T13:51:50Z",
                "oldest_thread_date": None,
                "newest_thread_date": None,
                "total_threads": 1,
            },
            "threads": ["not-a-dict"],
        }
        cache_manager.cache_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "encrypted": True,
                    "cache": encrypt_token(json.dumps(invalid_inner_cache)),
                    "created_at": "2025-12-23T13:51:50Z",
                }
            ),
            encoding="utf-8",
        )
        os.chmod(cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS)

        with pytest.raises(ConfigurationError, match="Cache content has invalid format"):
            cache_manager.load_cache()

    def test_load_cache_rejects_malformed_coverage_dates(self, cache_manager):
        """Malformed cache coverage dates are treated as corrupt config."""
        from perplexity_cli.utils.encryption import encrypt_token

        malformed_coverage_cache = {
            "version": 1,
            "metadata": {
                "last_sync_time": "2025-12-23T13:51:50Z",
                "oldest_thread_date": "not-a-date",
                "newest_thread_date": "2025-12-23T13:51:50Z",
                "total_threads": 1,
            },
            "threads": [],
        }
        cache_manager.cache_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "encrypted": True,
                    "cache": encrypt_token(json.dumps(malformed_coverage_cache)),
                    "created_at": "2025-12-23T13:51:50Z",
                }
            ),
            encoding="utf-8",
        )
        os.chmod(cache_manager.cache_path, cache_manager.SECURE_PERMISSIONS)

        with pytest.raises(ConfigurationError, match="Cache content has invalid format"):
            cache_manager.load_cache()


class TestCacheInvalidation:
    """Test cache invalidation logic."""

    @pytest.fixture
    def cached_threads(self):
        """Threads from 2025-12-21 to 2025-12-23."""
        return [
            ThreadRecord(
                title="Newest",
                url="https://example.com/newest",
                created_at="2025-12-23T15:30:00Z",
            ),
            ThreadRecord(
                title="Middle",
                url="https://example.com/middle",
                created_at="2025-12-22T12:00:00Z",
            ),
            ThreadRecord(
                title="Oldest",
                url="https://example.com/oldest",
                created_at="2025-12-21T08:00:00Z",
            ),
        ]

    def test_requires_fresh_data_no_cache(self, cache_manager):
        """Test that missing cache requires fresh data."""
        needs_fresh, _from_d, _to_d = cache_manager.requires_fresh_data("2025-12-22", "2025-12-23")
        assert needs_fresh is True

    def test_requires_fresh_data_range_within_cache(self, cache_manager, cached_threads):
        """Test that range fully covered by cache doesn't need refresh (before newest date)."""
        cache_manager.save_cache(cached_threads)

        # Request range that ends before cache_newest_date
        needs_fresh, from_d, to_d = cache_manager.requires_fresh_data("2025-12-21", "2025-12-22")
        assert needs_fresh is False
        assert from_d is None
        assert to_d is None

    def test_requires_fresh_data_range_extends_beyond_cache(self, cache_manager, cached_threads):
        """Test that range extending beyond cache needs refresh."""
        cache_manager.save_cache(cached_threads)

        needs_fresh, from_d, to_d = cache_manager.requires_fresh_data("2025-12-22", "2025-12-24")
        assert needs_fresh is True
        # Should fetch from cache_newest_date (2025-12-23) not 2025-12-24
        assert from_d == "2025-12-23"
        assert to_d == "2025-12-24"

    def test_requires_fresh_data_range_before_cache(self, cache_manager, cached_threads):
        """Test that range before cache needs refresh."""
        cache_manager.save_cache(cached_threads)

        needs_fresh, from_d, to_d = cache_manager.requires_fresh_data("2025-12-20", "2025-12-21")
        assert needs_fresh is True
        assert from_d == "2025-12-20"
        assert to_d == "2025-12-21"

    def test_requires_fresh_data_includes_cache_newest_date(self, cache_manager, cached_threads):
        """Test that fetch range includes cache_newest_date (same-day refetch)."""
        cache_manager.save_cache(cached_threads)

        # Request exactly matches cache newest date
        needs_fresh, from_d, to_d = cache_manager.requires_fresh_data("2025-12-23", "2025-12-23")
        # Should still fetch because range matches cache_newest_date
        # (may have additional threads added that day)
        assert needs_fresh is True
        assert from_d == "2025-12-23"
        assert to_d == "2025-12-23"

    def test_requires_fresh_data_with_no_to_date(self, cache_manager, cached_threads):
        """Test that missing to_date uses today's date."""
        cache_manager.save_cache(cached_threads)

        needs_fresh, from_d, _to_d = cache_manager.requires_fresh_data("2025-12-22", None)
        # Since to_date is None, it should default to today
        # Today is definitely after cache_newest_date
        assert needs_fresh is True
        assert from_d == "2025-12-23"

    def test_requires_fresh_data_rejects_non_strict_date(self, cache_manager):
        """Non YYYY-MM-DD dates are rejected before any cache access."""
        with pytest.raises(ValueError, match="Invalid from_date"):
            cache_manager.requires_fresh_data("2026-1-1", None)

    def test_requires_fresh_data_rejects_from_after_to(self, cache_manager):
        """from_date after to_date is rejected before any cache access."""
        with pytest.raises(ValueError, match="Invalid date range"):
            cache_manager.requires_fresh_data("2026-02-01", "2026-01-01")


class TestThreadMerging:
    """Test thread deduplication and merging."""

    def test_merge_eliminates_duplicates(self, cache_manager):
        """Test that merge eliminates duplicate URLs."""
        cached = [
            ThreadRecord(
                title="Thread 1",
                url="https://example.com/1",
                created_at="2025-12-23T13:00:00Z",
            ),
            ThreadRecord(
                title="Thread 2",
                url="https://example.com/2",
                created_at="2025-12-22T12:00:00Z",
            ),
        ]

        new = [
            ThreadRecord(
                title="Thread 3",
                url="https://example.com/3",
                created_at="2025-12-24T14:00:00Z",
            ),
            ThreadRecord(
                # Duplicate URL, should be ignored
                title="Thread 1 Updated",
                url="https://example.com/1",
                created_at="2025-12-23T13:30:00Z",
            ),
        ]

        merged = cache_manager.merge_threads(cached, new)

        # Should have 3 unique threads (duplicate ignored)
        assert len(merged) == 3
        urls = [t.url for t in merged]
        assert len(set(urls)) == 3  # All unique

    def test_merge_preserves_cached_threads(self, cache_manager):
        """Test that cached threads are preserved (never overwritten)."""
        cached = [
            ThreadRecord(
                title="Original Title",
                url="https://example.com/1",
                created_at="2025-12-23T13:00:00Z",
            ),
        ]

        new = [
            ThreadRecord(
                title="Updated Title",
                url="https://example.com/1",
                created_at="2025-12-23T13:30:00Z",
            ),
        ]

        merged = cache_manager.merge_threads(cached, new)

        # Should keep cached version (original title)
        assert merged[0].title == "Original Title"

    def test_merge_sorts_newest_first(self, cache_manager):
        """Test that merge result is sorted newest-first."""
        cached = [
            ThreadRecord(
                title="December 21",
                url="https://example.com/1",
                created_at="2025-12-21T08:00:00Z",
            ),
        ]

        new = [
            ThreadRecord(
                title="December 24",
                url="https://example.com/3",
                created_at="2025-12-24T15:00:00Z",
            ),
            ThreadRecord(
                title="December 22",
                url="https://example.com/2",
                created_at="2025-12-22T10:00:00Z",
            ),
        ]

        merged = cache_manager.merge_threads(cached, new)

        # Should be sorted newest first
        assert merged[0].created_at == "2025-12-24T15:00:00Z"
        assert merged[1].created_at == "2025-12-22T10:00:00Z"
        assert merged[2].created_at == "2025-12-21T08:00:00Z"

    def test_merge_empty_cached(self, cache_manager):
        """Test merge when cache is empty."""
        new = [
            ThreadRecord(
                title="New 1",
                url="https://example.com/1",
                created_at="2025-12-23T13:00:00Z",
            ),
            ThreadRecord(
                title="New 2",
                url="https://example.com/2",
                created_at="2025-12-22T12:00:00Z",
            ),
        ]

        merged = cache_manager.merge_threads([], new)

        assert len(merged) == 2
        assert merged[0].title == "New 1"  # Newest first

    def test_merge_empty_new(self, cache_manager):
        """Test merge when new threads are empty."""
        cached = [
            ThreadRecord(
                title="Cached 1",
                url="https://example.com/1",
                created_at="2025-12-23T13:00:00Z",
            ),
        ]

        merged = cache_manager.merge_threads(cached, [])

        assert len(merged) == 1
        assert merged[0].title == "Cached 1"


class TestCacheEncryption:
    """Test that cache encryption is machine-specific."""

    def test_encrypted_content_not_plaintext(self, cache_manager):
        """Test that encrypted cache content is not readable plaintext."""
        threads = [
            ThreadRecord(
                title="Secret Thread",
                url="https://example.com/secret",
                created_at="2025-12-23T13:00:00Z",
            ),
        ]

        cache_manager.save_cache(threads)

        # Read raw file
        with open(cache_manager.cache_path, encoding="utf-8") as f:
            content = f.read()

        # Should not contain plaintext thread title
        assert "Secret Thread" not in content
        assert "https://example.com/secret" not in content

    def test_encrypted_cache_roundtrip(self, cache_manager):
        """Test that encrypted cache can be read back correctly."""
        threads = [
            ThreadRecord(
                title="Thread A",
                url="https://example.com/a",
                created_at="2025-12-23T13:00:00Z",
            ),
            ThreadRecord(
                title="Thread B",
                url="https://example.com/b",
                created_at="2025-12-22T12:00:00Z",
            ),
        ]

        cache_manager.save_cache(threads)
        loaded = cache_manager.load_cache()

        assert len(loaded["threads"]) == 2
        assert loaded["threads"][0]["title"] == "Thread A"
        assert loaded["threads"][1]["title"] == "Thread B"


class TestThreadCacheConversion:
    """Test defensive cached-thread conversion."""

    def test_convert_cache_dicts_rejects_non_dict_entry(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread record"):
            convert_cache_dicts_to_thread_records([{}])

    def test_convert_cache_dicts_rejects_missing_key(self):
        with pytest.raises(UpstreamSchemaError, match="missing url"):
            convert_cache_dicts_to_thread_records(
                [{"title": "Thread 1", "created_at": "2025-12-23T13:51:50Z"}]
            )


class TestThreadCacheCoverageBranches:
    """Focused tests for cache-manager error and edge branches."""

    def test_parse_coverage_date_malformed_raises_configuration_error(self) -> None:
        from perplexity_cli.threads.cache_manager import _parse_coverage_timestamp

        with pytest.raises(ConfigurationError, match="Malformed cache coverage date"):
            _parse_coverage_timestamp("not-a-date")

    def test_parse_thread_timestamp_malformed_raises_configuration_error(self) -> None:
        from perplexity_cli.threads.cache_manager import _parse_thread_timestamp

        with pytest.raises(ConfigurationError, match="Malformed cached thread timestamp"):
            _parse_thread_timestamp("garbage")

    def test_default_cache_path_from_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:

        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        expected = tmp_path / "threads-cache.json"
        monkeypatch.setattr(
            "perplexity_cli.threads.cache_manager.get_config_paths",
            lambda: type("Paths", (), {"cache_path": expected})(),
        )
        manager = ThreadCacheManager()
        assert manager.cache_path == expected

    def test_load_cache_corrupt_json_raises_oserror(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{invalid json", encoding="utf-8")
        os.chmod(cache_file, 0o600)
        manager = ThreadCacheManager(cache_path=cache_file)
        with pytest.raises(OSError, match="Failed to load cache"):
            manager.load_cache()

    def test_validate_outer_format_invalid_version(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        manager = ThreadCacheManager(cache_path=tmp_path / "cache.json")
        with pytest.raises(ConfigurationError, match="invalid format"):
            manager._validate_outer_format({"version": 999})

    def test_validate_outer_format_unencrypted(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        manager = ThreadCacheManager(cache_path=tmp_path / "cache.json")
        with pytest.raises(ConfigurationError, match="not encrypted"):
            manager._validate_outer_format({"version": 1, "encrypted": False, "cache": "x"})

    def test_save_cache_write_failure_raises_oserror(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        cache_dir = tmp_path / "cache-dir"
        cache_dir.mkdir()
        manager = ThreadCacheManager(cache_path=cache_dir)  # a directory, not a file
        with pytest.raises(OSError, match="Failed to save"):
            manager.save_cache([])

    def test_get_cache_coverage_load_failure_returns_none(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        cache_file = tmp_path / "cache.json"
        cache_file.write_text("{broken", encoding="utf-8")
        manager = ThreadCacheManager(cache_path=cache_file)
        assert manager.get_cache_coverage() == (None, None)

    def test_parse_cache_coverage_missing_metadata_returns_none(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        manager = ThreadCacheManager(cache_path=tmp_path / "cache.json")
        assert manager._parse_cache_coverage() is None

    def test_clear_cache_failure_raises_oserror(self, tmp_path) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        locked_dir = tmp_path / "locked"
        locked_dir.mkdir()
        cache_file = locked_dir / "cache.json"
        cache_file.write_text("{}", encoding="utf-8")
        os.chmod(cache_file, 0o600)
        os.chmod(locked_dir, 0o500)
        manager = ThreadCacheManager(cache_path=cache_file)
        try:
            with pytest.raises(OSError, match="Failed to delete cache file"):
                manager.clear_cache()
        finally:
            os.chmod(locked_dir, 0o700)

    def test_build_metadata_empty_threads(self) -> None:
        from perplexity_cli.threads.cache_manager import ThreadCacheManager

        manager = ThreadCacheManager(cache_path=None)
        metadata = manager._build_cache_metadata([])
        assert metadata["oldest_thread_date"] is None
        assert metadata["newest_thread_date"] is None
        assert metadata["total_threads"] == 0
