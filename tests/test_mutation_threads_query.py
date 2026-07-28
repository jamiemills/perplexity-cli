"""Round 2 mutation-killing tests for threads/, query_runner, and query_streaming.

Targets survivors missed by the first round: exact string literals, arithmetic
boundaries, constant values, return-value structures, and comparison edges.
"""

from __future__ import annotations

import csv
import json
import os
import time
from datetime import UTC, date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from perplexity_cli.api.models import Answer, QueryInput, TraceContext, WebResult
from perplexity_cli.formatting.context import OutputOptions, RenderContext
from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.threads.date_parser import (
    _check_after_start,
    _check_before_end,
    _parse_day_end,
    _parse_day_start,
    is_in_date_range,
    parse_absolute_date_string,
    to_iso8601,
)
from perplexity_cli.threads.exporter import ThreadRecord, write_threads_csv
from perplexity_cli.threads.models import (
    CacheContent,
    CacheFormat,
    CacheMetadata,
    DateRange,
    _validate_thread_dict,
)
from perplexity_cli.threads.scraper import (
    _DEFAULT_TIMEOUT_SECONDS,
    _LEGACY_CONTEXT_ARG_LIMIT,
    _PROGRESS_CALLBACK_ARG_INDEX,
    _THREAD_PAGE_SIZE,
    _TOTAL_THREADS_ARG_INDEX,
    BatchProcessingContext,
    ThreadScraper,
    _build_batch_processing_context,
    _build_legacy_batch_processing_context,
    _convert_cache_thread_dicts,
    _extract_total_threads,
    _get_cache_str_field,
    _get_str_field,
    _handle_http_error,
    _has_more_pages,
    _is_in_date_range,
    _is_progress_callback,
    _parse_single_thread,
    _report_progress,
    _to_iso8601,
    _validate_batch_processing_arg_count,
    _validate_date_params,
)
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    ConfigurationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    SimpleResponse,
    UpstreamSchemaError,
)
from perplexity_cli.utils.logging import get_logger


def _rec(title: str, url: str, created_at: str) -> ThreadRecord:
    return ThreadRecord(title=title, url=url, created_at=created_at)


# ---------------------------------------------------------------------------
# scraper.py – constants
# ---------------------------------------------------------------------------


class TestScraperConstants:
    """Pin module-level constants to kill constant-mutation survivors."""

    def test_default_timeout_seconds(self):
        assert _DEFAULT_TIMEOUT_SECONDS == 30

    def test_thread_page_size(self):
        assert _THREAD_PAGE_SIZE == 100

    def test_legacy_context_arg_limit(self):
        assert _LEGACY_CONTEXT_ARG_LIMIT == 3

    def test_total_threads_arg_index(self):
        assert _TOTAL_THREADS_ARG_INDEX == 1

    def test_progress_callback_arg_index(self):
        assert _PROGRESS_CALLBACK_ARG_INDEX == 2


# ---------------------------------------------------------------------------
# scraper.py – _build_auth_context
# ---------------------------------------------------------------------------


class TestBuildAuthContext:
    """Kill mutations in cookie/header construction."""

    def test_content_type_header(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        headers, _ = scraper._build_auth_context("sess-tok")
        assert headers["Content-Type"] == "application/json"

    def test_session_token_cookie_name(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        _, cookies = scraper._build_auth_context("sess-tok")
        assert cookies["__Secure-next-auth.session-token"] == "sess-tok"

    def test_existing_cookies_preserved(self):
        scraper = ThreadScraper(
            token='{"user": {"accessToken": "t"}}',
            cookies={"cf_clearance": "abc"},
        )
        _, cookies = scraper._build_auth_context("sess-tok")
        assert cookies["cf_clearance"] == "abc"
        assert cookies["__Secure-next-auth.session-token"] == "sess-tok"

    def test_existing_session_cookie_not_overwritten(self):
        scraper = ThreadScraper(
            token='{"user": {"accessToken": "t"}}',
            cookies={"__Secure-next-auth.session-token": "existing"},
        )
        _, cookies = scraper._build_auth_context("new-tok")
        assert cookies["__Secure-next-auth.session-token"] == "existing"

    def test_none_cookies_yields_empty_dict_plus_token(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cookies=None)
        _, cookies = scraper._build_auth_context("tok")
        assert cookies == {"__Secure-next-auth.session-token": "tok"}


# ---------------------------------------------------------------------------
# scraper.py – _parse_single_thread URL construction
# ---------------------------------------------------------------------------


class TestParseSingleThreadUrl:
    """Kill mutations in URL construction and default field values."""

    def test_url_contains_slug(self):
        record, _ = _parse_single_thread(
            {"last_query_datetime": "2026-01-15T10:00:00+00:00", "slug": "my-slug", "title": "T"},
            None,
        )
        assert record is not None
        assert "/search/my-slug" in record.url

    def test_url_uses_base_url(self):
        record, _ = _parse_single_thread(
            {"last_query_datetime": "2026-01-15T10:00:00+00:00", "slug": "s", "title": "T"},
            None,
        )
        assert record is not None
        assert record.url.startswith("https://")

    def test_default_slug_is_empty_string(self):
        record, _ = _parse_single_thread(
            {"last_query_datetime": "2026-01-15T10:00:00+00:00", "title": "T"},
            None,
        )
        assert record is not None
        assert record.url.endswith("/search/")

    def test_default_title_is_untitled(self):
        record, _ = _parse_single_thread(
            {"last_query_datetime": "2026-01-15T10:00:00+00:00", "slug": "s"},
            None,
        )
        assert record is not None
        assert record.title == "Untitled"

    def test_created_at_is_iso8601_with_z(self):
        record, _ = _parse_single_thread(
            {"last_query_datetime": "2026-01-15T10:30:00+00:00", "slug": "s", "title": "T"},
            None,
        )
        assert record is not None
        assert record.created_at == "2026-01-15T10:30:00Z"

    def test_from_date_boundary_inclusive(self):
        record, should_stop = _parse_single_thread(
            {"last_query_datetime": "2026-01-01T00:00:00+00:00", "slug": "s", "title": "T"},
            "2026-01-01",
        )
        assert should_stop is False
        assert record is not None

    def test_from_date_one_day_before_cutoff(self):
        record, should_stop = _parse_single_thread(
            {"last_query_datetime": "2025-12-31T23:59:59+00:00", "slug": "s", "title": "T"},
            "2026-01-01",
        )
        assert should_stop is True
        assert record is None


# ---------------------------------------------------------------------------
# scraper.py – _handle_http_error exact messages
# ---------------------------------------------------------------------------


class TestHandleHttpErrorMessages:
    """Kill string-literal mutations in error messages."""

    def test_401_message_content(self):
        resp = SimpleResponse(status_code=401)
        err = PerplexityHTTPStatusError("err", response=resp)
        with pytest.raises(AuthenticationError, match="Authentication failed"):
            _handle_http_error(err)

    def test_401_message_mentions_re_auth(self):
        resp = SimpleResponse(status_code=401)
        err = PerplexityHTTPStatusError("err", response=resp)
        with pytest.raises(AuthenticationError, match="perplexity-cli auth"):
            _handle_http_error(err)

    def test_429_message_content(self):
        resp = SimpleResponse(status_code=429)
        err = PerplexityHTTPStatusError("err", response=resp)
        with pytest.raises(RateLimitError, match="Rate limit exceeded"):
            _handle_http_error(err)

    def test_429_message_mentions_try_again(self):
        resp = SimpleResponse(status_code=429)
        err = PerplexityHTTPStatusError("err", response=resp)
        with pytest.raises(RateLimitError, match="try again later"):
            _handle_http_error(err)

    def test_500_reraises_original(self):
        resp = SimpleResponse(status_code=500)
        err = PerplexityHTTPStatusError("server error", response=resp)
        with pytest.raises(PerplexityHTTPStatusError):
            try:
                raise err
            except PerplexityHTTPStatusError as exc:
                _handle_http_error(exc)

    def test_403_reraises_original(self):
        resp = SimpleResponse(status_code=403)
        err = PerplexityHTTPStatusError("forbidden", response=resp)
        with pytest.raises(PerplexityHTTPStatusError):
            try:
                raise err
            except PerplexityHTTPStatusError as exc:
                _handle_http_error(exc)


# ---------------------------------------------------------------------------
# scraper.py – _convert_cache_thread_dicts
# ---------------------------------------------------------------------------


class TestConvertCacheThreadDicts:
    """Kill mutations in cache-to-record conversion."""

    def test_all_fields_mapped(self):
        dicts = [{"title": "T", "url": "U", "created_at": "C"}]
        records = _convert_cache_thread_dicts(dicts)
        assert records[0].title == "T"
        assert records[0].url == "U"
        assert records[0].created_at == "C"

    def test_missing_title_raises(self):
        with pytest.raises(UpstreamSchemaError, match="missing title"):
            _convert_cache_thread_dicts([{"url": "U", "created_at": "C"}])

    def test_missing_url_raises(self):
        with pytest.raises(UpstreamSchemaError, match="missing url"):
            _convert_cache_thread_dicts([{"title": "T", "created_at": "C"}])

    def test_missing_created_at_raises(self):
        with pytest.raises(UpstreamSchemaError, match="missing created_at"):
            _convert_cache_thread_dicts([{"title": "T", "url": "U"}])

    def test_non_string_value_raises(self):
        with pytest.raises(UpstreamSchemaError, match="missing title"):
            _convert_cache_thread_dicts([{"title": 42, "url": "U", "created_at": "C"}])

    def test_empty_list_returns_empty(self):
        assert _convert_cache_thread_dicts([]) == []


# ---------------------------------------------------------------------------
# scraper.py – _filter_by_date_range
# ---------------------------------------------------------------------------


class TestFilterByDateRange:
    """Kill mutations in date-range filtering logic."""

    def _make_scraper(self) -> ThreadScraper:
        return ThreadScraper(token='{"user": {"accessToken": "t"}}')

    def test_no_filters_returns_all(self):
        scraper = self._make_scraper()
        threads = [_rec("A", "u1", "2026-01-15T10:00:00Z")]
        assert scraper._filter_by_date_range(threads, None, None) == threads

    def test_z_suffix_parsed_correctly(self):
        scraper = self._make_scraper()
        threads = [_rec("A", "u1", "2026-06-15T12:00:00Z")]
        result = scraper._filter_by_date_range(threads, "2026-06-15", "2026-06-15")
        assert len(result) == 1

    def test_from_date_excludes_older(self):
        scraper = self._make_scraper()
        threads = [
            _rec("New", "u1", "2026-02-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-15T00:00:00Z"),
        ]
        result = scraper._filter_by_date_range(threads, "2026-02-01", None)
        assert len(result) == 1
        assert result[0].title == "New"

    def test_to_date_excludes_newer(self):
        scraper = self._make_scraper()
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-15T00:00:00Z"),
        ]
        result = scraper._filter_by_date_range(threads, None, "2026-02-01")
        assert len(result) == 1
        assert result[0].title == "Old"

    def test_both_bounds_inclusive(self):
        scraper = self._make_scraper()
        threads = [
            _rec("Start", "u1", "2026-01-01T00:00:00Z"),
            _rec("Mid", "u2", "2026-01-15T12:00:00Z"),
            _rec("End", "u3", "2026-01-31T23:59:59Z"),
        ]
        result = scraper._filter_by_date_range(threads, "2026-01-01", "2026-01-31")
        assert len(result) == 3


# ---------------------------------------------------------------------------
# scraper.py – _merge_with_cache
# ---------------------------------------------------------------------------


class TestMergeWithCache:
    """Kill mutations in merge logic."""

    def test_no_cached_returns_fetched(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        fetched = [_rec("F", "u1", "2026-01-01T00:00:00Z")]
        result = scraper._merge_with_cache([], fetched)
        assert result is fetched

    def test_no_cache_manager_returns_fetched(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=None)
        cached = [_rec("C", "u0", "2026-01-01T00:00:00Z")]
        fetched = [_rec("F", "u1", "2026-01-02T00:00:00Z")]
        result = scraper._merge_with_cache(cached, fetched)
        assert result is fetched

    def test_with_cache_manager_delegates(self):
        cm = MagicMock()
        merged = [_rec("M", "u1", "2026-01-01T00:00:00Z")]
        cm.merge_threads.return_value = merged
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}', cache_manager=cm)
        cached = [_rec("C", "u0", "2026-01-01T00:00:00Z")]
        fetched = [_rec("F", "u1", "2026-01-02T00:00:00Z")]
        result = scraper._merge_with_cache(cached, fetched)
        assert result is merged
        cm.merge_threads.assert_called_once_with(cached, fetched)


# ---------------------------------------------------------------------------
# scraper.py – _process_thread_batch with BatchProcessingContext
# ---------------------------------------------------------------------------


class TestProcessThreadBatchContext:
    """Kill mutations in batch processing with typed context."""

    def test_context_object_passthrough(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        ctx = BatchProcessingContext(from_date=None, total_threads=5, progress_callback=None)
        data = [{"last_query_datetime": "2026-06-01T00:00:00+00:00", "slug": "s", "title": "T"}]
        stopped = scraper._process_thread_batch(data, threads, ctx)
        assert stopped is False
        assert len(threads) == 1

    def test_progress_callback_receives_total_threads(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        cb = Mock()
        ctx = BatchProcessingContext(from_date=None, total_threads=42, progress_callback=cb)
        data = [
            {
                "last_query_datetime": "2026-06-01T00:00:00+00:00",
                "slug": "s",
                "title": "T",
            }
        ]
        scraper._process_thread_batch(data, threads, ctx)
        cb.assert_called_once_with(1, 42)

    def test_legacy_three_args(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        cb = Mock()
        data = [{"last_query_datetime": "2026-06-01T00:00:00+00:00", "slug": "s", "title": "T"}]
        stopped = scraper._process_thread_batch(data, threads, "2026-01-01", 10, cb)
        assert stopped is False
        cb.assert_called_once_with(1, 10)

    def test_four_args_raises_type_error(self):
        scraper = ThreadScraper(token='{"user": {"accessToken": "t"}}')
        threads: list[ThreadRecord] = []
        with pytest.raises(TypeError, match="at most three"):
            scraper._process_thread_batch(
                [{"last_query_datetime": "2026-06-01T00:00:00+00:00", "slug": "s", "title": "T"}],
                threads,
                "a", "b", "c", "d",
            )


# ---------------------------------------------------------------------------
# scraper.py – _build_legacy_batch_processing_context indices
# ---------------------------------------------------------------------------


class TestBuildLegacyBatchContext:
    """Kill index-mutation survivors in legacy context builder."""

    def test_from_date_at_index_zero(self):
        ctx = _build_legacy_batch_processing_context(("2025-01-01",))
        assert ctx.from_date == "2025-01-01"

    def test_total_threads_at_index_one(self):
        ctx = _build_legacy_batch_processing_context((None, 99))
        assert ctx.total_threads == 99

    def test_progress_callback_at_index_two(self):
        cb = lambda c, t: None
        ctx = _build_legacy_batch_processing_context((None, None, cb))
        assert ctx.progress_callback is cb

    def test_all_none(self):
        ctx = _build_legacy_batch_processing_context(())
        assert ctx.from_date is None
        assert ctx.total_threads is None
        assert ctx.progress_callback is None


# ---------------------------------------------------------------------------
# scraper.py – _is_progress_callback
# ---------------------------------------------------------------------------


class TestIsProgressCallback:
    """Kill mutations in callable check."""

    def test_callable_returns_true(self):
        assert _is_progress_callback(lambda c, t: None) is True

    def test_non_callable_returns_false(self):
        assert _is_progress_callback("not callable") is False

    def test_none_returns_false(self):
        assert _is_progress_callback(None) is False


# ---------------------------------------------------------------------------
# scraper.py – _validate_date_params exact messages
# ---------------------------------------------------------------------------


class TestValidateDateParamsMessages:
    """Kill string mutations in validation error messages."""

    def test_from_date_message_includes_label(self):
        with pytest.raises(ValueError, match="Invalid from_date 'garbage'"):
            _validate_date_params("garbage", None)

    def test_to_date_message_includes_label(self):
        with pytest.raises(ValueError, match="Invalid to_date 'junk'"):
            _validate_date_params(None, "junk")

    def test_message_includes_format_hint(self):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _validate_date_params("bad", None)


# ---------------------------------------------------------------------------
# scraper.py – _get_str_field
# ---------------------------------------------------------------------------


class TestGetStrFieldEdgeCases:
    """Kill mutations in field extraction."""

    def test_default_none_raises_when_missing(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed thread slug"):
            _get_str_field({}, "slug")

    def test_explicit_default_used(self):
        assert _get_str_field({}, "title", "Untitled") == "Untitled"

    def test_empty_string_default(self):
        assert _get_str_field({}, "slug", "") == ""

    def test_non_string_value_with_default_still_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed thread title"):
            _get_str_field({"title": 123}, "title", "fallback")


# ---------------------------------------------------------------------------
# scraper.py – _extract_total_threads
# ---------------------------------------------------------------------------


class TestExtractTotalThreadsEdgeCases:
    """Kill mutations in total-thread extraction."""

    def test_existing_total_not_overridden(self):
        assert _extract_total_threads({"total_threads": 999}, 42) == 42

    def test_none_total_reads_dict(self):
        assert _extract_total_threads({"total_threads": 7}, None) == 7

    def test_missing_key_defaults_zero(self):
        assert _extract_total_threads({}, None) == 0

    def test_string_value_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed total_threads"):
            _extract_total_threads({"total_threads": "ten"}, None)

    def test_float_value_raises(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed total_threads"):
            _extract_total_threads({"total_threads": 3.14}, None)

    def test_bool_value_accepted_as_int(self):
        assert _extract_total_threads({"total_threads": True}, None) is True


# ---------------------------------------------------------------------------
# scraper.py – _has_more_pages
# ---------------------------------------------------------------------------


class TestHasMorePagesEdgeCases:
    """Kill mutations in pagination check."""

    def test_truthy_non_bool_value(self):
        assert _has_more_pages([{"has_next_page": 1}]) is True

    def test_falsy_zero_value(self):
        assert _has_more_pages([{"has_next_page": 0}]) is False

    def test_second_entry_ignored(self):
        assert _has_more_pages([{"has_next_page": False}, {"has_next_page": True}]) is False


# ---------------------------------------------------------------------------
# scraper.py – _report_progress
# ---------------------------------------------------------------------------


class TestReportProgressEdgeCases:
    """Kill mutations in progress reporting."""

    def test_none_total_skips(self):
        cb = Mock()
        _report_progress(cb, 10, None)
        cb.assert_not_called()

    def test_zero_total_skips(self):
        cb = Mock()
        _report_progress(cb, 10, 0)
        cb.assert_not_called()

    def test_none_callback_with_total(self):
        _report_progress(None, 10, 100)

    def test_exact_values_passed(self):
        cb = Mock()
        _report_progress(cb, 7, 42)
        cb.assert_called_once_with(7, 42)


# ---------------------------------------------------------------------------
# cache_manager.py – constants
# ---------------------------------------------------------------------------


class TestCacheManagerConstants:
    """Pin cache manager constants."""

    def test_secure_permissions(self):
        assert ThreadCacheManager.SECURE_PERMISSIONS == 0o600

    def test_cache_version(self):
        assert ThreadCacheManager.CACHE_VERSION == 1


# ---------------------------------------------------------------------------
# cache_manager.py – merge_threads
# ---------------------------------------------------------------------------


class TestMergeThreadsEdgeCases:
    """Kill mutations in merge/dedup logic."""

    def test_duplicate_within_fetched_eliminated(self, cache_manager):
        cached = [_rec("C", "u0", "2026-01-01T00:00:00Z")]
        fetched = [
            _rec("F1", "u1", "2026-01-02T00:00:00Z"),
            _rec("F1-dup", "u1", "2026-01-03T00:00:00Z"),
        ]
        merged = cache_manager.merge_threads(cached, fetched)
        urls = [t.url for t in merged]
        assert urls.count("u1") == 1

    def test_sort_reverse_true(self, cache_manager):
        cached = [_rec("Old", "u1", "2026-01-01T00:00:00Z")]
        fetched = [_rec("New", "u2", "2026-06-01T00:00:00Z")]
        merged = cache_manager.merge_threads(cached, fetched)
        assert merged[0].created_at > merged[1].created_at

    def test_cached_version_kept_on_duplicate(self, cache_manager):
        cached = [_rec("Original", "u1", "2026-01-01T00:00:00Z")]
        fetched = [_rec("Updated", "u1", "2026-01-01T00:00:00Z")]
        merged = cache_manager.merge_threads(cached, fetched)
        assert len(merged) == 1
        assert merged[0].title == "Original"

    def test_empty_both(self, cache_manager):
        assert cache_manager.merge_threads([], []) == []


# ---------------------------------------------------------------------------
# cache_manager.py – _build_cache_metadata
# ---------------------------------------------------------------------------


class TestBuildCacheMetadataEdgeCases:
    """Kill mutations in metadata construction."""

    def test_oldest_is_last_element(self, cache_manager):
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Mid", "u2", "2026-02-01T00:00:00Z"),
            _rec("Old", "u3", "2026-01-01T00:00:00Z"),
        ]
        meta = cache_manager._build_cache_metadata(threads)
        assert meta["oldest_thread_date"] == "2026-01-01T00:00:00Z"

    def test_newest_is_first_element(self, cache_manager):
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-01T00:00:00Z"),
        ]
        meta = cache_manager._build_cache_metadata(threads)
        assert meta["newest_thread_date"] == "2026-03-01T00:00:00Z"

    def test_total_threads_count(self, cache_manager):
        threads = [_rec("A", "u1", "2026-01-01T00:00:00Z"), _rec("B", "u2", "2026-01-02T00:00:00Z")]
        meta = cache_manager._build_cache_metadata(threads)
        assert meta["total_threads"] == 2

    def test_empty_threads_none_dates(self, cache_manager):
        meta = cache_manager._build_cache_metadata([])
        assert meta["oldest_thread_date"] is None
        assert meta["newest_thread_date"] is None
        assert meta["total_threads"] == 0

    def test_last_sync_time_present(self, cache_manager):
        meta = cache_manager._build_cache_metadata([])
        assert "last_sync_time" in meta


# ---------------------------------------------------------------------------
# cache_manager.py – _calculate_fetch_range boundaries
# ---------------------------------------------------------------------------


class TestCalculateFetchRangeBoundaries:
    """Kill comparison mutations in fetch-range calculation."""

    def test_request_from_equals_cache_oldest_no_older(self):
        needs, _, _ = ThreadCacheManager._calculate_fetch_range(
            date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 1), date(2026, 1, 31)
        )
        assert needs is False

    def test_request_from_one_day_before_cache_oldest(self):
        needs, fetch_from, _ = ThreadCacheManager._calculate_fetch_range(
            date(2025, 12, 31), date(2026, 1, 15), date(2026, 1, 1), date(2026, 1, 31)
        )
        assert needs is True
        assert fetch_from == "2025-12-31"

    def test_request_to_one_day_before_cache_newest_no_fetch(self):
        needs, _, _ = ThreadCacheManager._calculate_fetch_range(
            date(2026, 1, 5), date(2026, 1, 30), date(2026, 1, 1), date(2026, 1, 31)
        )
        assert needs is False

    def test_request_to_equals_cache_newest_needs_fetch(self):
        needs, _, _ = ThreadCacheManager._calculate_fetch_range(
            date(2026, 1, 5), date(2026, 1, 31), date(2026, 1, 1), date(2026, 1, 31)
        )
        assert needs is True

    def test_fetch_from_is_cache_newest_when_only_newer_needed(self):
        needs, fetch_from, fetch_to = ThreadCacheManager._calculate_fetch_range(
            date(2026, 1, 5), date(2026, 2, 15), date(2026, 1, 1), date(2026, 1, 31)
        )
        assert needs is True
        assert fetch_from == "2026-01-31"
        assert fetch_to == "2026-02-15"


# ---------------------------------------------------------------------------
# cache_manager.py – requires_fresh_data
# ---------------------------------------------------------------------------


class TestRequiresFreshDataEdgeCases:
    """Kill mutations in requires_fresh_data."""

    def test_no_cache_returns_true_with_original_dates(self, cache_manager):
        needs, fetch_from, fetch_to = cache_manager.requires_fresh_data("2026-01-01", "2026-06-01")
        assert needs is True
        assert fetch_from == "2026-01-01"
        assert fetch_to == "2026-06-01"

    def test_no_cache_none_dates(self, cache_manager):
        needs, fetch_from, fetch_to = cache_manager.requires_fresh_data(None, None)
        assert needs is True
        assert fetch_from is None
        assert fetch_to is None

    def test_from_date_none_uses_cache_oldest(self, cache_manager):
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-01T00:00:00Z"),
        ]
        cache_manager.save_cache(threads)
        needs, _, _ = cache_manager.requires_fresh_data(None, "2026-02-01")
        assert needs is False


# ---------------------------------------------------------------------------
# cache_manager.py – save_cache outer format
# ---------------------------------------------------------------------------


class TestSaveCacheOuterFormat:
    """Kill mutations in the outer cache file structure."""

    def test_outer_format_fields(self, cache_manager):
        cache_manager.save_cache([_rec("T", "U", "2026-01-01T00:00:00Z")])
        with open(cache_manager.cache_path, encoding="utf-8") as f:
            outer = json.load(f)
        assert outer["version"] == 1
        assert outer["encrypted"] is True
        assert isinstance(outer["cache"], str)
        assert "created_at" in outer

    def test_thread_dict_fields_in_decrypted(self, cache_manager):
        cache_manager.save_cache([_rec("T", "U", "2026-01-01T00:00:00Z")])
        loaded = cache_manager.load_cache()
        thread = loaded["threads"][0]
        assert set(thread.keys()) == {"title", "url", "created_at"}


# ---------------------------------------------------------------------------
# cache_manager.py – _parse_cache_coverage
# ---------------------------------------------------------------------------


class TestParseCacheCoverage:
    """Kill mutations in coverage parsing."""

    def test_no_cache_returns_none(self, cache_manager):
        assert cache_manager._parse_cache_coverage() is None

    def test_incomplete_metadata_returns_none(self, cache_manager):
        cache_manager.save_cache([])
        result = cache_manager._parse_cache_coverage()
        assert result is None

    def test_complete_metadata_returns_dates(self, cache_manager):
        threads = [
            _rec("New", "u1", "2026-03-01T00:00:00Z"),
            _rec("Old", "u2", "2026-01-01T00:00:00Z"),
        ]
        cache_manager.save_cache(threads)
        result = cache_manager._parse_cache_coverage()
        assert result is not None
        oldest, newest = result
        assert oldest == date(2026, 1, 1)
        assert newest == date(2026, 3, 1)


# ---------------------------------------------------------------------------
# date_parser.py – parse_absolute_date_string
# ---------------------------------------------------------------------------


class TestParseAbsoluteDateStringEdgeCases:
    """Kill mutations in GMT replacement and timezone handling."""

    def test_gmt_replaced_with_utc(self):
        result = parse_absolute_date_string(
            "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"
        )
        assert result.tzinfo is not None

    def test_result_hour_is_13_for_1pm(self):
        result = parse_absolute_date_string(
            "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"
        )
        assert result.hour == 13

    def test_result_minute(self):
        result = parse_absolute_date_string(
            "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"
        )
        assert result.minute == 51

    def test_result_second(self):
        result = parse_absolute_date_string(
            "Tuesday, December 23, 2025 at 1:51:50 PM Greenwich Mean Time"
        )
        assert result.second == 50

    def test_error_message_includes_original(self):
        with pytest.raises(ValueError, match="not a date"):
            parse_absolute_date_string("not a date")


# ---------------------------------------------------------------------------
# date_parser.py – to_iso8601 slice mutation
# ---------------------------------------------------------------------------


class TestToIso8601Slice:
    """Kill the [:-6] + 'Z' slice mutation."""

    def test_utc_offset_replaced_with_z(self):
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2026-01-15T10:30:00Z"
        assert "+00:00" not in result

    def test_naive_gets_z_suffix(self):
        dt = datetime(2026, 1, 15, 10, 30, 0)
        result = to_iso8601(dt)
        assert result.endswith("Z")

    def test_microseconds_preserved(self):
        dt = datetime(2026, 1, 15, 10, 30, 0, 500000, tzinfo=UTC)
        result = to_iso8601(dt)
        assert result == "2026-01-15T10:30:00.500000Z"


# ---------------------------------------------------------------------------
# date_parser.py – _parse_day_start / _parse_day_end exact values
# ---------------------------------------------------------------------------


class TestParseDayBoundaries:
    """Kill arithmetic mutations in day-boundary parsing."""

    def test_day_start_hour_is_zero(self):
        assert _parse_day_start("2026-06-15", UTC).hour == 0

    def test_day_start_minute_is_zero(self):
        assert _parse_day_start("2026-06-15", UTC).minute == 0

    def test_day_start_second_is_zero(self):
        assert _parse_day_start("2026-06-15", UTC).second == 0

    def test_day_start_microsecond_is_zero(self):
        assert _parse_day_start("2026-06-15", UTC).microsecond == 0

    def test_day_end_hour_is_23(self):
        assert _parse_day_end("2026-06-15", UTC).hour == 23

    def test_day_end_minute_is_59(self):
        assert _parse_day_end("2026-06-15", UTC).minute == 59

    def test_day_end_second_is_59(self):
        assert _parse_day_end("2026-06-15", UTC).second == 59

    def test_day_end_microsecond_is_999999(self):
        assert _parse_day_end("2026-06-15", UTC).microsecond == 999999

    def test_day_start_tzinfo_applied(self):
        result = _parse_day_start("2026-06-15", UTC)
        assert result.tzinfo is UTC

    def test_day_end_tzinfo_applied(self):
        result = _parse_day_end("2026-06-15", UTC)
        assert result.tzinfo is UTC


# ---------------------------------------------------------------------------
# date_parser.py – is_in_date_range error message
# ---------------------------------------------------------------------------


class TestIsInDateRangeErrorMessage:
    """Kill string mutations in error message."""

    def test_error_includes_from_date_value(self):
        dt = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="from_date='bad'"):
            is_in_date_range(dt, "bad", None)

    def test_error_includes_to_date_value(self):
        dt = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="to_date='bad'"):
            is_in_date_range(dt, None, "bad")

    def test_error_includes_format_hint(self):
        dt = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            is_in_date_range(dt, "bad", None)


# ---------------------------------------------------------------------------
# date_parser.py – _check_after_start / _check_before_end boundaries
# ---------------------------------------------------------------------------


class TestCheckBoundaries:
    """Kill comparison mutations at exact boundaries."""

    def test_after_start_one_microsecond_before(self):
        dt = datetime(2026, 5, 31, 23, 59, 59, 999999, tzinfo=UTC)
        assert _check_after_start(dt, "2026-06-01") is False

    def test_after_start_exact_midnight(self):
        dt = datetime(2026, 6, 1, 0, 0, 0, 0, tzinfo=UTC)
        assert _check_after_start(dt, "2026-06-01") is True

    def test_before_end_one_microsecond_after(self):
        dt = datetime(2026, 7, 1, 0, 0, 0, 0, tzinfo=UTC)
        assert _check_before_end(dt, "2026-06-30") is False

    def test_before_end_exact_end_of_day(self):
        dt = datetime(2026, 6, 30, 23, 59, 59, 999999, tzinfo=UTC)
        assert _check_before_end(dt, "2026-06-30") is True


# ---------------------------------------------------------------------------
# exporter.py – CSV column order and format
# ---------------------------------------------------------------------------


class TestCsvExportFormat:
    """Kill mutations in CSV output format."""

    def test_header_exact_order(self, tmp_path):
        out = tmp_path / "t.csv"
        write_threads_csv([_rec("T", "U", "2026-01-01T00:00:00Z")], out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == ["created_at", "title", "url"]

    def test_row_order_created_at_first(self, tmp_path):
        out = tmp_path / "t.csv"
        write_threads_csv([_rec("MyTitle", "https://x.com", "2026-01-01T00:00:00Z")], out)
        with open(out, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)
            row = next(reader)
        assert row[0] == "2026-01-01T00:00:00Z"
        assert row[1] == "MyTitle"
        assert row[2] == "https://x.com"

    def test_default_filename_prefix(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        write_threads_csv([_rec("T", "U", "2026-01-01T00:00:00Z")])
        csv_files = list(tmp_path.glob("threads-*.csv"))
        assert len(csv_files) == 1

    def test_default_filename_extension(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = write_threads_csv([_rec("T", "U", "2026-01-01T00:00:00Z")])
        assert result.suffix == ".csv"

    def test_empty_records_error_message(self):
        with pytest.raises(ValueError, match="Cannot write CSV with empty records list"):
            write_threads_csv([])

    def test_os_error_wrapped(self, tmp_path):
        bad_path = tmp_path / "nonexistent_dir" / "file.csv"
        with pytest.raises(OSError, match="Failed to write CSV"):
            write_threads_csv([_rec("T", "U", "C")], bad_path)


# ---------------------------------------------------------------------------
# models.py – _validate_thread_dict
# ---------------------------------------------------------------------------


class TestValidateThreadDict:
    """Kill mutations in thread dict validation."""

    def test_valid_dict_returns_true(self):
        assert _validate_thread_dict({"url": "U", "title": "T"}) is True

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a dictionary"):
            _validate_thread_dict("not a dict")

    def test_missing_url_raises(self):
        with pytest.raises(ValueError, match="must have a 'url' field"):
            _validate_thread_dict({"title": "T"})

    def test_missing_title_raises(self):
        with pytest.raises(ValueError, match="must have a 'title' field"):
            _validate_thread_dict({"url": "U"})

    def test_list_raises(self):
        with pytest.raises(ValueError, match="must be a dictionary"):
            _validate_thread_dict(["url", "title"])


# ---------------------------------------------------------------------------
# models.py – CacheFormat version constraints
# ---------------------------------------------------------------------------


class TestCacheFormatConstraints:
    """Kill mutations in version constraints."""

    def test_version_zero_rejected(self):
        with pytest.raises(Exception):
            CacheFormat(version=0, cache="data")

    def test_version_two_rejected(self):
        with pytest.raises(Exception):
            CacheFormat(version=2, cache="data")

    def test_version_one_accepted(self):
        fmt = CacheFormat(version=1, cache="data")
        assert fmt.version == 1

    def test_encrypted_default_true(self):
        fmt = CacheFormat(cache="data")
        assert fmt.encrypted is True


# ---------------------------------------------------------------------------
# models.py – CacheContent version constraints
# ---------------------------------------------------------------------------


class TestCacheContentConstraints:
    """Kill mutations in CacheContent version constraints."""

    def test_version_zero_rejected(self):
        meta = CacheMetadata(last_sync_time=datetime(2025, 1, 1, tzinfo=UTC))
        with pytest.raises(Exception):
            CacheContent(version=0, metadata=meta)

    def test_version_two_rejected(self):
        meta = CacheMetadata(last_sync_time=datetime(2025, 1, 1, tzinfo=UTC))
        with pytest.raises(Exception):
            CacheContent(version=2, metadata=meta)

    def test_empty_threads_default(self):
        meta = CacheMetadata(last_sync_time=datetime(2025, 1, 1, tzinfo=UTC))
        content = CacheContent(version=1, metadata=meta)
        assert content.threads == []


# ---------------------------------------------------------------------------
# query_runner.py – _QUERY_JSON_COMMAND constant
# ---------------------------------------------------------------------------


class TestQueryJsonCommand:
    """Pin the command string constant."""

    def test_command_string(self):
        from perplexity_cli.query_runner import _QUERY_JSON_COMMAND

        assert _QUERY_JSON_COMMAND == "pxcli query --json"


# ---------------------------------------------------------------------------
# query_runner.py – build_final_query format
# ---------------------------------------------------------------------------


class TestBuildFinalQueryFormat:
    """Kill string-format mutations."""

    def test_double_newline_separator(self):
        with patch("perplexity_cli.query_runner.StyleManager") as mock_sm:
            mock_sm.return_value.load_style.return_value = "style text"
            from perplexity_cli.query_runner import build_final_query

            result = build_final_query("query")
        assert result == "query\n\nstyle text"

    def test_no_style_returns_original(self):
        with patch("perplexity_cli.query_runner.StyleManager") as mock_sm:
            mock_sm.return_value.load_style.return_value = ""
            from perplexity_cli.query_runner import build_final_query

            result = build_final_query("query")
        assert result == "query"

    def test_none_style_returns_original(self):
        with patch("perplexity_cli.query_runner.StyleManager") as mock_sm:
            mock_sm.return_value.load_style.return_value = None
            from perplexity_cli.query_runner import build_final_query

            result = build_final_query("query")
        assert result == "query"


# ---------------------------------------------------------------------------
# query_runner.py – _build_json_envelope reference structure
# ---------------------------------------------------------------------------


class TestBuildJsonEnvelopeStructure:
    """Kill mutations in JSON envelope reference dict."""

    def test_reference_has_name_url_snippet(self):
        from perplexity_cli.query_runner import _build_json_envelope

        answer = Answer(
            text="A",
            references=[WebResult(name="N", url="https://u.com", snippet="S")],
        )
        trace = TraceContext(trace_id="t", start_time=time.monotonic())
        result = json.loads(_build_json_envelope(answer, trace, "no_schema"))
        ref = result["result"]["references"][0]
        assert set(ref.keys()) == {"name", "url", "snippet"}
        assert ref["name"] == "N"
        assert ref["url"] == "https://u.com"
        assert ref["snippet"] == "S"

    def test_envelope_command_field(self):
        from perplexity_cli.query_runner import _build_json_envelope

        answer = Answer(text="A", references=[])
        trace = TraceContext(trace_id="t", start_time=time.monotonic())
        result = json.loads(_build_json_envelope(answer, trace, "no_schema"))
        assert result["command"] == "pxcli query --json"

    def test_envelope_ok_true(self):
        from perplexity_cli.query_runner import _build_json_envelope

        answer = Answer(text="A", references=[])
        trace = TraceContext(trace_id="t", start_time=time.monotonic())
        result = json.loads(_build_json_envelope(answer, trace, "no_schema"))
        assert result["ok"] is True

    def test_trailing_newline(self):
        from perplexity_cli.query_runner import _build_json_envelope

        answer = Answer(text="A", references=[])
        trace = TraceContext(trace_id="t", start_time=time.monotonic())
        result = _build_json_envelope(answer, trace, "no_schema")
        assert result.endswith("\n")


# ---------------------------------------------------------------------------
# query_runner.py – _read_query_from_stdin messages
# ---------------------------------------------------------------------------


class TestReadQueryFromStdinMessages:
    """Kill string mutations in stdin error messages."""

    def test_tty_error_message(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        with patch("perplexity_cli.query_runner.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            with pytest.raises(SystemExit) as exc_info:
                _read_query_from_stdin("-")
            assert exc_info.value.code == 2

    def test_empty_input_error_message(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        with patch("perplexity_cli.query_runner.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.read.return_value = ""
            with pytest.raises(SystemExit) as exc_info:
                _read_query_from_stdin("-")
            assert exc_info.value.code == 2

    def test_whitespace_stripped(self):
        from perplexity_cli.query_runner import _read_query_from_stdin

        with patch("perplexity_cli.query_runner.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.read.return_value = "  hello  "
            assert _read_query_from_stdin("-") == "hello"


# ---------------------------------------------------------------------------
# query_runner.py – _require_auth_for_attachments
# ---------------------------------------------------------------------------


class TestRequireAuthForAttachments:
    """Kill mutations in attachment auth check."""

    def test_valid_token_returned(self):
        from perplexity_cli.query_runner import _require_auth_for_attachments

        logger = get_logger()
        assert _require_auth_for_attachments("tok", logger) == "tok"

    def test_none_token_exits_1(self):
        from perplexity_cli.query_runner import _require_auth_for_attachments

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _require_auth_for_attachments(None, logger)
        assert exc_info.value.code == 1

    def test_empty_token_exits_1(self):
        from perplexity_cli.query_runner import _require_auth_for_attachments

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _require_auth_for_attachments("", logger)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# query_runner.py – _try_dispatch_known_error messages
# ---------------------------------------------------------------------------


class TestTryDispatchKnownErrorMessages:
    """Kill string mutations in error dispatch."""

    def test_configuration_error_exits_1(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _try_dispatch_known_error(ConfigurationError("bad config"), logger, "normal")
        assert exc_info.value.code == 1

    def test_attachment_error_exits_1(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error
        from perplexity_cli.utils.exceptions import AttachmentError

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _try_dispatch_known_error(AttachmentError("bad attachment"), logger, "normal")
        assert exc_info.value.code == 1

    def test_http_status_error_returns_true(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        resp = SimpleResponse(status_code=500)
        err = PerplexityHTTPStatusError("err", response=resp)
        with patch("perplexity_cli.query_runner.handle_http_error"):
            assert _try_dispatch_known_error(err, logger, "normal") is True

    def test_request_error_returns_true(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        with patch("perplexity_cli.query_runner.handle_network_error"):
            assert _try_dispatch_known_error(PerplexityRequestError("net"), logger, "normal") is True

    def test_runtime_error_returns_false(self):
        from perplexity_cli.query_runner import _try_dispatch_known_error

        logger = get_logger()
        assert _try_dispatch_known_error(RuntimeError("x"), logger, "normal") is False


# ---------------------------------------------------------------------------
# query_runner.py – _handle_fallback_error
# ---------------------------------------------------------------------------


class TestHandleFallbackError:
    """Kill mutations in fallback error handler."""

    def test_message_tuple_content(self):
        from perplexity_cli.query_runner import _handle_fallback_error

        logger = get_logger()
        with patch("perplexity_cli.query_runner.handle_unexpected_cli_error") as mock_handle:
            mock_handle.side_effect = SystemExit(1)
            with pytest.raises(SystemExit):
                _handle_fallback_error(RuntimeError("x"), logger, "normal")
        msg_tuple = mock_handle.call_args.kwargs["message_tuple"]
        assert msg_tuple[0] == "[ERROR] An unexpected error occurred."
        assert msg_tuple[1] == "Unexpected error"
        assert msg_tuple[2] is True


# ---------------------------------------------------------------------------
# query_runner.py – render_complete_answer
# ---------------------------------------------------------------------------


class TestRenderCompleteAnswer:
    """Kill mutations in render branching."""

    def test_rich_calls_render_complete(self):
        from perplexity_cli.query_runner import render_complete_answer

        formatter = Mock()
        opts = OutputOptions(output_format="rich", strip_references=False, json_mode=False)
        render = RenderContext(formatter=formatter, options=opts)
        answer = Answer(text="A", references=[])
        render_complete_answer(answer, render)
        formatter.render_complete.assert_called_once()

    def test_plain_calls_format_complete(self):
        from perplexity_cli.query_runner import render_complete_answer

        formatter = Mock()
        formatter.format_complete.return_value = "output"
        opts = OutputOptions(output_format="plain", strip_references=False, json_mode=False)
        render = RenderContext(formatter=formatter, options=opts)
        answer = Answer(text="A", references=[])
        with patch("perplexity_cli.query_runner.click.echo") as mock_echo:
            render_complete_answer(answer, render)
        mock_echo.assert_called_once_with("output")


# ---------------------------------------------------------------------------
# query_streaming.py – _write_ndjson_result command string
# ---------------------------------------------------------------------------


class TestWriteNdjsonResultCommand:
    """Kill command-string mutations."""

    def test_command_is_pxcli_query_json_stream(self):
        from perplexity_cli.ndjson import NDJSONWriter
        from perplexity_cli.query_streaming import _write_ndjson_result

        output = StringIO()
        writer = NDJSONWriter(output)
        trace = TraceContext(start_time=time.monotonic(), trace_id="t")
        _write_ndjson_result(writer, "text", [], trace)
        data = json.loads(output.getvalue().strip())
        assert data["command"] == "pxcli query --json --stream"

    def test_ok_is_true(self):
        from perplexity_cli.ndjson import NDJSONWriter
        from perplexity_cli.query_streaming import _write_ndjson_result

        output = StringIO()
        writer = NDJSONWriter(output)
        trace = TraceContext(start_time=time.monotonic(), trace_id="t")
        _write_ndjson_result(writer, "text", [], trace)
        data = json.loads(output.getvalue().strip())
        assert data["ok"] is True

    def test_meta_has_version(self):
        from perplexity_cli.ndjson import NDJSONWriter
        from perplexity_cli.query_streaming import _write_ndjson_result

        output = StringIO()
        writer = NDJSONWriter(output)
        trace = TraceContext(start_time=time.monotonic(), trace_id="t")
        _write_ndjson_result(writer, "text", [], trace)
        data = json.loads(output.getvalue().strip())
        assert "version" in data["meta"]

    def test_duration_ms_is_int(self):
        from perplexity_cli.ndjson import NDJSONWriter
        from perplexity_cli.query_streaming import _write_ndjson_result

        output = StringIO()
        writer = NDJSONWriter(output)
        trace = TraceContext(start_time=time.monotonic(), trace_id="t")
        _write_ndjson_result(writer, "text", [], trace)
        data = json.loads(output.getvalue().strip())
        assert isinstance(data["meta"]["duration_ms"], int)


# ---------------------------------------------------------------------------
# query_streaming.py – error handler messages
# ---------------------------------------------------------------------------


class TestStreamErrorHandlerMessages:
    """Kill string mutations in stream error handlers."""

    def test_upstream_schema_error_message(self):
        from perplexity_cli.query_streaming import _handle_stream_upstream_schema_error

        logger = get_logger()
        with patch("perplexity_cli.query_streaming.click.echo"):
            with pytest.raises(SystemExit) as exc_info:
                _handle_stream_upstream_schema_error(UpstreamSchemaError("bad"), logger)
        assert exc_info.value.code == 1

    def test_keyboard_interrupt_message(self):
        from perplexity_cli.query_streaming import _handle_stream_keyboard_interrupt

        logger = get_logger()
        with pytest.raises(SystemExit) as exc_info:
            _handle_stream_keyboard_interrupt(logger)
        assert exc_info.value.code == 130

    def test_output_error_message(self):
        from perplexity_cli.query_streaming import _handle_stream_output_error

        logger = get_logger()
        with patch("perplexity_cli.query_streaming.click.echo"):
            with pytest.raises(SystemExit) as exc_info:
                _handle_stream_output_error(OSError("broken pipe"), logger)
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# query_streaming.py – _init_stream_error_handlers order
# ---------------------------------------------------------------------------


class TestInitStreamErrorHandlers:
    """Kill mutations in handler table construction."""

    def test_five_handlers(self):
        from perplexity_cli.query_streaming import _init_stream_error_handlers

        handlers = _init_stream_error_handlers()
        assert len(handlers) == 5

    def test_first_handler_is_http_status(self):
        from perplexity_cli.query_streaming import _init_stream_error_handlers

        handlers = _init_stream_error_handlers()
        assert handlers[0][0] is PerplexityHTTPStatusError

    def test_second_handler_is_request_error(self):
        from perplexity_cli.query_streaming import _init_stream_error_handlers

        handlers = _init_stream_error_handlers()
        assert handlers[1][0] is PerplexityRequestError

    def test_third_handler_is_upstream_schema(self):
        from perplexity_cli.query_streaming import _init_stream_error_handlers

        handlers = _init_stream_error_handlers()
        assert handlers[2][0] is UpstreamSchemaError

    def test_fourth_handler_is_keyboard_interrupt(self):
        from perplexity_cli.query_streaming import _init_stream_error_handlers

        handlers = _init_stream_error_handlers()
        assert handlers[3][0] is KeyboardInterrupt

    def test_fifth_handler_is_click_and_oserror(self):
        from perplexity_cli.query_streaming import _init_stream_error_handlers
        from click import ClickException

        handlers = _init_stream_error_handlers()
        assert handlers[4][0] == (ClickException, OSError)


# ---------------------------------------------------------------------------
# query_streaming.py – _process_stream_message slice
# ---------------------------------------------------------------------------


class TestProcessStreamMessageSlice:
    """Kill slice-mutation in text[len(accumulated):]."""

    def test_exact_increment(self):
        from perplexity_cli.query_streaming import _process_stream_message

        msg = Mock()
        msg.extract_answer_text.return_value = "Hello world"
        result = _process_stream_message(msg, "Hello", None)
        assert result == "Hello world"

    def test_first_chunk_from_empty(self):
        from perplexity_cli.query_streaming import _process_stream_message

        msg = Mock()
        msg.extract_answer_text.return_value = "First"
        result = _process_stream_message(msg, "", None)
        assert result == "First"

    def test_shorter_text_returns_accumulated(self):
        from perplexity_cli.query_streaming import _process_stream_message

        msg = Mock()
        msg.extract_answer_text.return_value = "Hi"
        result = _process_stream_message(msg, "Hello", None)
        assert result == "Hello"

    def test_ndjson_writer_gets_only_new_text(self):
        from perplexity_cli.query_streaming import _process_stream_message

        writer = Mock()
        msg = Mock()
        msg.extract_answer_text.return_value = "ABCDEF"
        _process_stream_message(msg, "ABC", writer)
        writer.chunk.assert_called_once_with("DEF")


# ---------------------------------------------------------------------------
# query_streaming.py – stream_query_response ndjson start command
# ---------------------------------------------------------------------------


class TestStreamQueryResponseNdjsonStart:
    """Kill ndjson start-command mutation."""

    def test_ndjson_start_command(self):
        from perplexity_cli.query_streaming import stream_query_response

        api = Mock()
        api.submit_query.return_value = iter([])
        opts = OutputOptions(output_format="plain", strip_references=True, json_mode=True)
        render = RenderContext(formatter=Mock(), options=opts)
        trace = TraceContext(trace_id="t")

        with patch("perplexity_cli.query_streaming.sys") as mock_sys:
            output = StringIO()
            mock_sys.stdout = output
            stream_query_response(api, QueryInput(query="q"), render, trace)

        lines = [line for line in output.getvalue().strip().split("\n") if line]
        start = json.loads(lines[0])
        assert start["type"] == "start"
        assert start["command"] == "pxcli query --json --stream"


# ---------------------------------------------------------------------------
# query_streaming.py – _handle_stream_error fallback
# ---------------------------------------------------------------------------


class TestHandleStreamErrorFallback:
    """Kill mutations in the fallback path of _handle_stream_error."""

    def test_unexpected_error_message_tuple(self):
        from perplexity_cli.query_streaming import _handle_stream_error

        with patch("perplexity_cli.query_streaming.handle_unexpected_cli_error") as mock_handle:
            mock_handle.side_effect = SystemExit(1)
            with pytest.raises(SystemExit):
                _handle_stream_error(RuntimeError("boom"))
        msg_tuple = mock_handle.call_args.kwargs["message_tuple"]
        assert msg_tuple[0] == "[ERROR] An unexpected error occurred."
        assert msg_tuple[1] == "Unexpected error during streaming"
        assert msg_tuple[2] is True


# ---------------------------------------------------------------------------
# scraper.py – _validate_batch_processing_arg_count boundary
# ---------------------------------------------------------------------------


class TestValidateBatchArgCountBoundary:
    """Kill boundary mutations at exactly 3 vs 4."""

    def test_exactly_three_ok(self):
        _validate_batch_processing_arg_count(3)

    def test_exactly_four_raises(self):
        with pytest.raises(TypeError, match="at most three"):
            _validate_batch_processing_arg_count(4)

    def test_two_ok(self):
        _validate_batch_processing_arg_count(2)

    def test_one_ok(self):
        _validate_batch_processing_arg_count(1)

    def test_zero_ok(self):
        _validate_batch_processing_arg_count(0)

    def test_five_raises(self):
        with pytest.raises(TypeError, match="at most three"):
            _validate_batch_processing_arg_count(5)


# ---------------------------------------------------------------------------
# scraper.py – _get_cache_str_field exact message
# ---------------------------------------------------------------------------


class TestGetCacheStrFieldMessage:
    """Kill string mutations in cache field extraction."""

    def test_message_includes_field_name(self):
        with pytest.raises(UpstreamSchemaError, match="missing title"):
            _get_cache_str_field({}, "title")

    def test_message_format(self):
        with pytest.raises(UpstreamSchemaError, match="Malformed cached thread record"):
            _get_cache_str_field({"url": 42}, "url")
