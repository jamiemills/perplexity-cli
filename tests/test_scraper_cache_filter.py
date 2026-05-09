"""Tests for thread cache date-range filtering.

Verifies that the scraper only persists threads within the requested date
range to the cache, rather than caching every thread ever fetched.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.scraper import ThreadScraper, _validate_date_params


def _make_thread(title: str, date: str, slug: str) -> ThreadRecord:
    """Create a ThreadRecord with the given date."""
    return ThreadRecord(
        title=title,
        url=f"https://www.perplexity.ai/search/{slug}",
        created_at=date,
    )


# Threads spanning January and February 2026
_THREADS_ALL = [
    _make_thread("Feb 10", "2026-02-10T12:00:00Z", "feb-10"),
    _make_thread("Feb 05", "2026-02-05T09:00:00Z", "feb-05"),
    _make_thread("Jan 20", "2026-01-20T15:00:00Z", "jan-20"),
    _make_thread("Jan 10", "2026-01-10T08:00:00Z", "jan-10"),
    _make_thread("Dec 25", "2025-12-25T10:00:00Z", "dec-25"),
]


@pytest.fixture
def mock_cache_manager():
    """Provide a mock ThreadCacheManager."""
    cm = MagicMock()
    cm.requires_fresh_data.return_value = (True, None, None)
    cm.load_cache.return_value = None
    cm.save_cache = MagicMock()
    return cm


@pytest.fixture
def scraper(mock_cache_manager):
    """Provide a ThreadScraper wired to the mock cache manager."""
    return ThreadScraper(
        token='{"user": {"accessToken": "test-token"}}',
        cache_manager=mock_cache_manager,
    )


class TestCacheDateRangeFiltering:
    """Verify that only date-filtered threads are saved to cache."""

    @pytest.mark.asyncio
    async def test_save_cache_receives_filtered_threads(self, scraper, mock_cache_manager):
        """When from_date is provided, save_cache must receive only threads
        on or after that date — not the full fetched set."""
        with patch.object(
            scraper,
            "_fetch_all_threads_from_api",
            new_callable=AsyncMock,
            return_value=list(_THREADS_ALL),
        ):
            result = await scraper.scrape_all_threads(from_date="2026-02-01")

        # The returned list should contain only February threads
        assert len(result) == 2
        assert all("Feb" in t.title for t in result)

        # The cache should have received the same filtered list
        mock_cache_manager.save_cache.assert_called_once()
        cached_threads = mock_cache_manager.save_cache.call_args[0][0]
        assert len(cached_threads) == 2
        assert all("Feb" in t.title for t in cached_threads)

    @pytest.mark.asyncio
    async def test_save_cache_receives_filtered_threads_with_to_date(
        self, scraper, mock_cache_manager
    ):
        """When both from_date and to_date are provided, save_cache must
        receive only threads within that range."""
        with patch.object(
            scraper,
            "_fetch_all_threads_from_api",
            new_callable=AsyncMock,
            return_value=list(_THREADS_ALL),
        ):
            result = await scraper.scrape_all_threads(from_date="2026-01-01", to_date="2026-01-31")

        assert len(result) == 2
        assert all("Jan" in t.title for t in result)

        cached_threads = mock_cache_manager.save_cache.call_args[0][0]
        assert len(cached_threads) == 2
        assert all("Jan" in t.title for t in cached_threads)

    @pytest.mark.asyncio
    async def test_save_cache_receives_all_threads_when_no_date_filter(
        self, scraper, mock_cache_manager
    ):
        """When no date range is specified, save_cache should receive
        all fetched threads."""
        with patch.object(
            scraper,
            "_fetch_all_threads_from_api",
            new_callable=AsyncMock,
            return_value=list(_THREADS_ALL),
        ):
            result = await scraper.scrape_all_threads()

        assert len(result) == 5

        cached_threads = mock_cache_manager.save_cache.call_args[0][0]
        assert len(cached_threads) == 5

    @pytest.mark.asyncio
    async def test_merged_threads_are_filtered_before_caching(self, scraper, mock_cache_manager):
        """When cache has old threads and API returns new ones, the merged
        set must be filtered before being saved to cache."""
        # Simulate existing cache with December thread
        cached_dec = [_make_thread("Dec 25", "2025-12-25T10:00:00Z", "dec-25")]
        mock_cache_manager.load_cache.return_value = {
            "threads": [
                {"title": t.title, "url": t.url, "created_at": t.created_at} for t in cached_dec
            ]
        }
        mock_cache_manager.merge_threads.return_value = list(_THREADS_ALL)

        # API returns February threads
        feb_threads = [
            _make_thread("Feb 10", "2026-02-10T12:00:00Z", "feb-10"),
            _make_thread("Feb 05", "2026-02-05T09:00:00Z", "feb-05"),
        ]

        with patch.object(
            scraper,
            "_fetch_all_threads_from_api",
            new_callable=AsyncMock,
            return_value=feb_threads,
        ):
            result = await scraper.scrape_all_threads(from_date="2026-02-01")

        # Result should be filtered to February only
        assert len(result) == 2

        # Cache should also be filtered — not the full merged set of 5
        cached_threads = mock_cache_manager.save_cache.call_args[0][0]
        assert len(cached_threads) == 2
        dates = [t.created_at for t in cached_threads]
        assert all(d.startswith("2026-02") for d in dates)


class TestThreadScraperRateLimiting:
    """Verify thread scraping rate limiting happens before requests."""

    @pytest.mark.asyncio
    async def test_rate_limiter_acquired_before_request(self, mock_cache_manager):
        """Test the scraper waits on the limiter before issuing a request."""
        rate_limiter = AsyncMock()
        rate_limiter.acquire.return_value = 0.0

        scraper = ThreadScraper(
            token='{"user": {"accessToken": "test-token"}}',
            cookies={"cf_clearance": "cookie"},
            rate_limiter=rate_limiter,
            cache_manager=mock_cache_manager,
        )

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = []

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = False

        with patch("perplexity_cli.utils.session_factory.AsyncSession", return_value=mock_context):
            await scraper._fetch_all_threads_from_api("test-token")

        rate_limiter.acquire.assert_awaited_once()
        mock_session.post.assert_awaited_once()


class TestThreadScraperMalformedPayloads:
    """Verify malformed upstream thread payloads fail explicitly."""

    @pytest.mark.asyncio
    async def test_fetch_threads_rejects_non_dict_entry(self, mock_cache_manager):
        scraper = ThreadScraper(
            token='{"user": {"accessToken": "test-token"}}', cache_manager=mock_cache_manager
        )

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = ["bad-entry"]

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = False

        with patch("perplexity_cli.utils.session_factory.AsyncSession", return_value=mock_context):
            with pytest.raises(RuntimeError, match="Malformed thread entry"):
                await scraper._fetch_all_threads_from_api("test-token")

    @pytest.mark.asyncio
    async def test_fetch_threads_rejects_missing_timestamp(self, mock_cache_manager):
        scraper = ThreadScraper(
            token='{"user": {"accessToken": "test-token"}}', cache_manager=mock_cache_manager
        )

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = [
            {"title": "No timestamp", "slug": "no-ts", "total_threads": 1}
        ]

        mock_session = AsyncMock()
        mock_session.post.return_value = mock_response

        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = False

        with patch("perplexity_cli.utils.session_factory.AsyncSession", return_value=mock_context):
            with pytest.raises(RuntimeError, match="Malformed thread last_query_datetime"):
                await scraper._fetch_all_threads_from_api("test-token")

    @pytest.mark.asyncio
    async def test_scrape_all_threads_rejects_invalid_session_user_shape(self, mock_cache_manager):
        scraper = ThreadScraper(token='{"user": "bad"}', cache_manager=mock_cache_manager)

        with pytest.raises(RuntimeError, match="invalid session user data"):
            await scraper.scrape_all_threads()


class TestDateValidation:
    """Tests for date parameter validation in scrape_all_threads."""

    def test_validate_date_params_accepts_valid_dates(self):
        """Valid YYYY-MM-DD strings should not raise."""
        _validate_date_params("2026-01-15", "2026-02-28")

    def test_validate_date_params_accepts_none(self):
        """None values should be accepted without error."""
        _validate_date_params(None, None)
        _validate_date_params("2026-01-01", None)
        _validate_date_params(None, "2026-12-31")

    def test_validate_date_params_rejects_garbage_from_date(self):
        """Unparseable from_date should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid from_date"):
            _validate_date_params("not-a-date", None)

    def test_validate_date_params_rejects_garbage_to_date(self):
        """Unparseable to_date should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid to_date"):
            _validate_date_params(None, "xyz")

    def test_validate_date_params_message_includes_value(self):
        """Error message should include the offending value."""
        with pytest.raises(ValueError, match="bad-value"):
            _validate_date_params("bad-value", None)

    @pytest.mark.asyncio
    async def test_scrape_all_threads_rejects_invalid_from_date(self):
        """scrape_all_threads should raise ValueError for unparseable from_date."""
        scraper = ThreadScraper(token="test-token")
        with pytest.raises(ValueError, match="Invalid from_date"):
            await scraper.scrape_all_threads(from_date="not-a-date")

    @pytest.mark.asyncio
    async def test_scrape_all_threads_rejects_invalid_to_date(self):
        """scrape_all_threads should raise ValueError for unparseable to_date."""
        scraper = ThreadScraper(token="test-token")
        with pytest.raises(ValueError, match="Invalid to_date"):
            await scraper.scrape_all_threads(to_date="abc123")
