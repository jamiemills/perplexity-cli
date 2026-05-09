"""Additional unit tests for ThreadScraper to improve branch coverage.

Covers uncovered lines in _try_cache_only, _prepare_fetch, _extract_total_threads,
_parse_single_thread, _handle_http_error, _make_api_request, _execute_api_post,
_has_more_pages, _process_thread_batch, _process_single_thread_entry,
_report_progress, and scrape_all_threads cache-hit path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.scraper import (
    ThreadScraper,
    _extract_total_threads,
    _handle_http_error,
    _has_more_pages,
    _parse_single_thread,
    _report_progress,
)
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    SimpleResponse,
    UpstreamSchemaError,
)


def _make_scraper(**kwargs) -> ThreadScraper:
    """Create a ThreadScraper with sensible defaults."""
    defaults = {"token": '{"user": {"accessToken": "tok"}}'}
    defaults.update(kwargs)
    return ThreadScraper(**defaults)


def _make_thread(title: str, date: str, slug: str = "s") -> ThreadRecord:
    return ThreadRecord(
        title=title,
        url=f"https://www.perplexity.ai/search/{slug}",
        created_at=date,
    )


# ---------------------------------------------------------------------------
# _try_cache_only
# ---------------------------------------------------------------------------


class TestTryCacheOnly:
    """Tests for the _try_cache_only fast-path."""

    def test_returns_none_when_no_cache_manager(self):
        """No cache_manager should return None immediately."""
        scraper = _make_scraper(cache_manager=None)
        assert scraper._try_cache_only(None, None) is None

    def test_returns_none_when_force_refresh(self):
        """force_refresh=True should bypass cache."""
        cm = MagicMock()
        scraper = _make_scraper(cache_manager=cm, force_refresh=True)
        assert scraper._try_cache_only(None, None) is None

    def test_returns_cached_threads_when_no_fresh_data_needed(self):
        """When cache covers the range, return filtered cached threads."""
        cm = MagicMock()
        cm.requires_fresh_data.return_value = (False, None, None)
        cm.load_cache.return_value = {
            "threads": [
                {
                    "title": "T1",
                    "url": "https://x.ai/search/a",
                    "created_at": "2026-01-15T00:00:00Z",
                },
            ]
        }
        scraper = _make_scraper(cache_manager=cm)
        result = scraper._try_cache_only(None, None)
        assert result is not None
        assert len(result) == 1
        assert result[0].title == "T1"


# ---------------------------------------------------------------------------
# _prepare_fetch
# ---------------------------------------------------------------------------


class TestPrepareFetch:
    """Tests for _prepare_fetch."""

    def test_force_refresh_ignores_cache(self):
        """force_refresh should return empty threads and pass-through dates."""
        cm = MagicMock()
        scraper = _make_scraper(cache_manager=cm, force_refresh=True)
        threads, ff, ft = scraper._prepare_fetch("2026-01-01", "2026-02-01")
        assert threads == []
        assert ff == "2026-01-01"
        assert ft == "2026-02-01"

    def test_no_cache_manager(self):
        """No cache_manager returns empty threads and pass-through dates."""
        scraper = _make_scraper(cache_manager=None)
        threads, ff, _ft = scraper._prepare_fetch("2026-01-01", None)
        assert threads == []
        assert ff == "2026-01-01"


# ---------------------------------------------------------------------------
# _extract_total_threads
# ---------------------------------------------------------------------------


class TestExtractTotalThreads:
    """Tests for _extract_total_threads."""

    def test_returns_existing_total_unchanged(self):
        """If total_threads is already known, return it unchanged."""
        assert _extract_total_threads({}, 42) == 42

    def test_falls_back_to_thread_dict(self):
        """When total_threads is None, extract from thread_dict."""
        assert _extract_total_threads({"total_threads": 10}, None) == 10

    def test_defaults_to_zero(self):
        """Missing key defaults to 0."""
        assert _extract_total_threads({}, None) == 0

    def test_raises_on_non_int(self):
        """Non-integer total_threads raises UpstreamSchemaError."""
        with pytest.raises(UpstreamSchemaError, match="Malformed total_threads"):
            _extract_total_threads({"total_threads": "bad"}, None)


# ---------------------------------------------------------------------------
# _parse_single_thread
# ---------------------------------------------------------------------------


class TestParseSingleThread:
    """Tests for _parse_single_thread."""

    def test_empty_timestamp_raises(self):
        """Empty timestamp string should raise UpstreamSchemaError."""
        with pytest.raises(UpstreamSchemaError, match="Malformed thread timestamp"):
            _parse_single_thread({"last_query_datetime": ""}, None)

    def test_thread_older_than_from_date(self):
        """Thread older than from_date returns (None, True)."""
        record, should_stop = _parse_single_thread(
            {"last_query_datetime": "2025-01-01T00:00:00", "slug": "s", "title": "T"},
            "2026-01-01",
        )
        assert record is None
        assert should_stop is True

    def test_valid_thread_returns_record(self):
        """Valid thread within range returns (ThreadRecord, False)."""
        record, should_stop = _parse_single_thread(
            {"last_query_datetime": "2026-06-01T12:00:00", "slug": "abc", "title": "Hello"},
            "2026-01-01",
        )
        assert record is not None
        assert should_stop is False
        assert record.title == "Hello"


# ---------------------------------------------------------------------------
# _handle_http_error
# ---------------------------------------------------------------------------


class TestHandleHttpError:
    """Tests for _handle_http_error."""

    def _make_error(self, status_code: int) -> PerplexityHTTPStatusError:
        resp = SimpleResponse(status_code=status_code)
        return PerplexityHTTPStatusError("err", response=resp)

    def test_401_raises_authentication_error(self):
        with pytest.raises(AuthenticationError):
            _handle_http_error(self._make_error(401))

    def test_429_raises_rate_limit_error(self):
        with pytest.raises(RateLimitError):
            _handle_http_error(self._make_error(429))

    @pytest.mark.asyncio
    async def test_other_status_re_raises(self):
        """Non-401/429 should re-raise the original PerplexityHTTPStatusError."""
        scraper = _make_scraper()
        err = self._make_error(500)
        with patch.object(scraper, "_execute_api_post", new_callable=AsyncMock, side_effect=err):
            with pytest.raises(PerplexityHTTPStatusError):
                await scraper._make_api_request(AsyncMock(), {}, {}, {})


# ---------------------------------------------------------------------------
# _make_api_request
# ---------------------------------------------------------------------------


class TestMakeApiRequest:
    """Tests for _make_api_request error handling paths."""

    @pytest.mark.asyncio
    async def test_http_error_delegates_to_handle(self):
        """PerplexityHTTPStatusError should be routed through _handle_http_error."""
        scraper = _make_scraper()
        resp = SimpleResponse(status_code=401)
        err = PerplexityHTTPStatusError("fail", response=resp)

        with patch.object(scraper, "_execute_api_post", new_callable=AsyncMock, side_effect=err):
            with pytest.raises(AuthenticationError):
                await scraper._make_api_request(AsyncMock(), {}, {}, {})

    @pytest.mark.asyncio
    async def test_network_error_converted(self):
        """RequestException should become PerplexityRequestError."""
        scraper = _make_scraper()

        from curl_cffi.requests.exceptions import RequestException

        with patch.object(
            scraper,
            "_execute_api_post",
            new_callable=AsyncMock,
            side_effect=RequestException("boom"),
        ):
            with pytest.raises(PerplexityRequestError, match="Network error"):
                await scraper._make_api_request(AsyncMock(), {}, {}, {})


# ---------------------------------------------------------------------------
# _execute_api_post
# ---------------------------------------------------------------------------


class TestExecuteApiPost:
    """Tests for _execute_api_post."""

    @pytest.mark.asyncio
    async def test_rate_limit_wait_logged(self):
        """When rate limiter returns wait_time > 0, it should be logged."""
        rl = AsyncMock()
        rl.acquire.return_value = 0.5
        scraper = _make_scraper(rate_limiter=rl)

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = []

        client = AsyncMock()
        client.post.return_value = mock_response

        result = await scraper._execute_api_post(client, {}, {}, {})
        assert result == []
        rl.acquire.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_ok_raises_http_status_error(self):
        """Non-OK response should raise via raise_http_status_error."""
        scraper = _make_scraper()

        mock_response = Mock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.headers = {}
        mock_response.url = "https://example.com"
        mock_response.request = Mock(method="POST", url="https://example.com")

        client = AsyncMock()
        client.post.return_value = mock_response

        with pytest.raises((PerplexityHTTPStatusError, Exception)):
            await scraper._execute_api_post(client, {}, {}, {})

    @pytest.mark.asyncio
    async def test_malformed_json_raises_upstream_schema_error(self):
        """When parse_thread_list_payload raises ValueError, wrap as UpstreamSchemaError."""
        scraper = _make_scraper()

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = "not-a-list"

        client = AsyncMock()
        client.post.return_value = mock_response

        with patch(
            "perplexity_cli.threads.scraper.parse_thread_list_payload",
            side_effect=ValueError("bad"),
        ):
            with pytest.raises(UpstreamSchemaError, match="Malformed thread list"):
                await scraper._execute_api_post(client, {}, {}, {})


# ---------------------------------------------------------------------------
# _has_more_pages
# ---------------------------------------------------------------------------


class TestHasMorePages:
    """Tests for _has_more_pages."""

    def test_empty_returns_false(self):
        assert _has_more_pages([]) is False

    def test_no_flag_returns_false(self):
        assert _has_more_pages([{"a": 1}]) is False

    def test_has_next_page_true(self):
        assert _has_more_pages([{"has_next_page": True}]) is True


# ---------------------------------------------------------------------------
# _process_thread_batch / _process_single_thread_entry
# ---------------------------------------------------------------------------


class TestProcessThreadBatch:
    """Tests for batch and single-entry processing."""

    def test_stops_on_from_date_cutoff(self):
        """Batch processing should return True when from_date cutoff reached."""
        scraper = _make_scraper()
        threads: list[ThreadRecord] = []
        data = [
            {"last_query_datetime": "2025-01-01T00:00:00", "slug": "s", "title": "Old"},
        ]
        stopped = scraper._process_thread_batch(data, threads, "2026-01-01", None, None)
        assert stopped is True

    def test_process_single_returns_true_on_should_stop(self):
        """_process_single_thread_entry returns True when thread is before from_date."""
        scraper = _make_scraper()
        threads: list[ThreadRecord] = []
        stopped = scraper._process_single_thread_entry(
            {"last_query_datetime": "2020-01-01T00:00:00", "slug": "s", "title": "T"},
            threads,
            "2026-01-01",
        )
        assert stopped is True
        assert len(threads) == 0

    def test_malformed_timestamp_raises_upstream_schema_error(self):
        """Invalid timestamp should raise UpstreamSchemaError."""
        scraper = _make_scraper()
        threads: list[ThreadRecord] = []
        with pytest.raises(UpstreamSchemaError, match="Malformed thread timestamp"):
            scraper._process_single_thread_entry(
                {"last_query_datetime": "not-a-date", "slug": "s", "title": "T"},
                threads,
                None,
            )


# ---------------------------------------------------------------------------
# _report_progress
# ---------------------------------------------------------------------------


class TestReportProgress:
    """Tests for _report_progress."""

    def test_callback_invoked(self):
        """Callback should be called with current and total."""
        cb = MagicMock()
        _report_progress(cb, 5, 10)
        cb.assert_called_once_with(5, 10)

    def test_no_callback_does_nothing(self):
        """None callback should not raise."""
        _report_progress(None, 5, 10)

    def test_zero_total_skips_callback(self):
        """Total of 0 (falsy) should not invoke callback."""
        cb = MagicMock()
        _report_progress(cb, 5, 0)
        cb.assert_not_called()


# ---------------------------------------------------------------------------
# scrape_all_threads cache-hit path (line 133)
# ---------------------------------------------------------------------------


class TestScrapeAllThreadsCacheHit:
    """Test that scrape_all_threads returns cached result on cache hit."""

    @pytest.mark.asyncio
    async def test_returns_cached_result_without_api_call(self):
        """When _try_cache_only returns data, no API call should be made."""
        cm = MagicMock()
        cm.requires_fresh_data.return_value = (False, None, None)
        cm.load_cache.return_value = {
            "threads": [
                {
                    "title": "Cached",
                    "url": "https://x.ai/search/c",
                    "created_at": "2026-03-01T00:00:00Z",
                },
            ]
        }
        scraper = _make_scraper(cache_manager=cm)

        with patch.object(scraper, "_fetch_and_merge", new_callable=AsyncMock) as mock_fetch:
            result = await scraper.scrape_all_threads()

        mock_fetch.assert_not_awaited()
        assert len(result) == 1
        assert result[0].title == "Cached"


# ---------------------------------------------------------------------------
# _fetch_all_threads_from_api: from_date cutoff & no-more-pages breaks
# ---------------------------------------------------------------------------


class TestFetchAllThreadsFromApi:
    """Tests for pagination break conditions."""

    @pytest.mark.asyncio
    async def test_from_date_cutoff_stops_pagination(self):
        """When a thread is older than from_date, pagination should stop."""
        scraper = _make_scraper()

        page1 = [
            {
                "last_query_datetime": "2026-06-01T00:00:00",
                "slug": "new",
                "title": "New",
                "has_next_page": True,
            },
            {
                "last_query_datetime": "2020-01-01T00:00:00",
                "slug": "old",
                "title": "Old",
                "has_next_page": True,
            },
        ]

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = page1

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch("perplexity_cli.utils.session_factory.AsyncSession", return_value=mock_ctx):
            result = await scraper._fetch_all_threads_from_api("tok", from_date="2025-01-01")

        # Only the newer thread should be returned; old one triggers stop
        assert len(result) == 1
        assert result[0].title == "New"
        # Should have made only one API call (stopped by cutoff)
        assert mock_session.post.await_count == 1

    @pytest.mark.asyncio
    async def test_no_more_pages_stops(self):
        """When has_next_page is absent/false, pagination stops."""
        scraper = _make_scraper()

        page1 = [
            {"last_query_datetime": "2026-06-01T00:00:00", "slug": "a", "title": "A"},
        ]

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = page1

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_session
        mock_ctx.__aexit__.return_value = False

        with patch("perplexity_cli.utils.session_factory.AsyncSession", return_value=mock_ctx):
            result = await scraper._fetch_all_threads_from_api("tok")

        assert len(result) == 1
        assert mock_session.post.await_count == 1
