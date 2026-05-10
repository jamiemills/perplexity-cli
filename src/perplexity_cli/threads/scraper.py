"""Thread scraping functionality for Perplexity.ai library.

This module handles automated extraction of thread data from the Perplexity.ai
API endpoint using stored authentication token. Supports local encrypted caching
for efficient repeated exports.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from dateutil import parser as dateutil_parser

try:
    from curl_cffi.requests.exceptions import RequestException

    _CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover
    RequestException = Exception  # type: ignore[assignment,misc]  # ty: ignore[invalid-assignment]
    _CURL_CFFI_AVAILABLE = False

if TYPE_CHECKING:
    from curl_cffi.requests import AsyncSession

from perplexity_cli.api.contracts import parse_thread_list_payload
from perplexity_cli.auth.utils import extract_session_token
from perplexity_cli.threads.cache_manager import ThreadCacheManager
from perplexity_cli.threads.date_parser import is_in_date_range, to_iso8601
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.utils import convert_cache_dicts_to_thread_records
from perplexity_cli.utils.config import get_perplexity_base_url, get_thread_list_url
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import raise_http_status_error
from perplexity_cli.utils.logging import get_logger
from perplexity_cli.utils.rate_limiter import RateLimiter
from perplexity_cli.utils.version import get_api_version

# ---------------------------------------------------------------------------
# Module-level utility functions (extracted from ThreadScraper)
# ---------------------------------------------------------------------------


def _create_async_session(timeout: int = 30) -> AsyncSession:
    """Create an AsyncSession with Chrome TLS impersonation.

    Args:
        timeout: Request timeout in seconds.

    Returns:
        An AsyncSession configured for Chrome impersonation.

    Raises:
        RuntimeError: If curl_cffi is not installed.
    """
    from perplexity_cli.utils.session_factory import create_async_session

    return create_async_session(timeout=timeout)


def _validate_date_params(from_date: str | None, to_date: str | None) -> None:
    """Validate that from_date and to_date are parseable date strings.

    Args:
        from_date: Start date string to validate (or None).
        to_date: End date string to validate (or None).

    Raises:
        ValueError: If either date string cannot be parsed.
    """
    for label, value in [("from_date", from_date), ("to_date", to_date)]:
        if value is not None:
            try:
                dateutil_parser.parse(value)
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"Invalid {label} '{value}': expected YYYY-MM-DD format") from exc


def _extract_total_threads(thread_dict: dict, total_threads: int | None) -> int:
    """Extract the total_threads count from an API response entry.

    Args:
        thread_dict: A single thread dictionary from the API response.
        total_threads: Previously known total, or None if not yet determined.

    Returns:
        The total_threads value (unchanged if already known).

    Raises:
        UpstreamSchemaError: If total_threads value is not an integer.
    """
    if total_threads is not None:
        return total_threads
    raw = thread_dict.get("total_threads", 0)
    if not isinstance(raw, int):
        raise UpstreamSchemaError("Malformed total_threads value in upstream API response")
    return raw


def _get_str_field(thread_dict: dict, field: str, default: str | None = None) -> str:
    """Extract a string field from a thread dict, raising on invalid type.

    Args:
        thread_dict: Thread data dictionary.
        field: Key to extract.
        default: Default value if key is absent. If None, field is required.

    Returns:
        The string value.

    Raises:
        UpstreamSchemaError: If value is not a string (or absent with no default).
    """
    value = thread_dict.get(field, default)
    if not isinstance(value, str):
        raise UpstreamSchemaError(f"Malformed thread {field} in upstream API response")
    return value


def _parse_single_thread(
    thread_dict: dict, from_date: str | None
) -> tuple[ThreadRecord | None, bool]:
    """Parse a single thread dictionary into a ThreadRecord.

    Args:
        thread_dict: Thread data from the API response.
        from_date: Optional lower date bound; if thread is older, signals stop.

    Returns:
        Tuple of (ThreadRecord or None, should_stop). Returns (None, True)
        when thread is older than from_date cutoff.

    Raises:
        UpstreamSchemaError: If required fields are malformed.
    """
    timestamp_str = _get_str_field(thread_dict, "last_query_datetime")
    if not timestamp_str:
        raise UpstreamSchemaError("Malformed thread timestamp in upstream API response")

    dt = datetime.fromisoformat(timestamp_str)
    if from_date and not is_in_date_range(dt, from_date, None):
        return None, True

    slug = _get_str_field(thread_dict, "slug", "")
    title = _get_str_field(thread_dict, "title", "Untitled")
    url = f"{get_perplexity_base_url()}/search/{slug}"
    return ThreadRecord(title=title, url=url, created_at=to_iso8601(dt)), False


def _handle_http_error(e: PerplexityHTTPStatusError) -> None:
    """Re-raise HTTP status errors as domain-specific exceptions.

    Args:
        e: The HTTP status error to handle.

    Raises:
        AuthenticationError: If status is 401.
        RateLimitError: If status is 429.
        PerplexityHTTPStatusError: For all other statuses.
    """
    if e.response.status_code == 401:
        raise AuthenticationError(
            "Authentication failed. Token may be expired. "
            "Please re-authenticate with: perplexity-cli auth"
        ) from e
    if e.response.status_code == 429:
        raise RateLimitError(
            "Rate limit exceeded while fetching threads. Please try again later."
        ) from e
    raise


def _has_more_pages(thread_data: list[dict]) -> bool:
    """Check whether the API response indicates more pages are available.

    Args:
        thread_data: Thread dictionaries from the current page.

    Returns:
        True if a next page exists.
    """
    if not thread_data:
        return False
    return bool(thread_data[0].get("has_next_page", False))


def _report_progress(
    callback: Callable[[int, int], None] | None,
    current: int,
    total: int | None,
) -> None:
    """Invoke progress callback if available.

    Args:
        callback: Optional progress callback.
        current: Current number of threads processed.
        total: Total expected threads, or None if unknown.
    """
    if callback and total:
        callback(current, total)


class ThreadScraper:
    """Scraper for extracting thread data from Perplexity.ai library.

    This class uses the /rest/thread/list_ask_threads API endpoint to fetch
    thread metadata including creation timestamps using the stored auth token.
    """

    def __init__(  # nosemgrep: boolean-flag-argument
        self,
        token: str,
        cookies: dict[str, str] | None = None,
        rate_limiter: RateLimiter | None = None,
        cache_manager: ThreadCacheManager | None = None,
        force_refresh: bool = False,
    ) -> None:
        """Initialise thread scraper.

        Args:
            token: Authentication token (from TokenManager)
            cookies: Optional browser cookies for Cloudflare/session reuse
            rate_limiter: Optional RateLimiter instance for request throttling
            cache_manager: Optional ThreadCacheManager for caching threads
            force_refresh: If True, ignore cache and fetch fresh data from API
        """
        self.token = token
        self.cookies = cookies
        self.rate_limiter = rate_limiter
        self.cache_manager = cache_manager
        self.force_refresh = force_refresh
        self.logger = get_logger()
        self.api_url = get_thread_list_url()
        self.api_version = get_api_version()

    async def scrape_all_threads(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ThreadRecord]:
        """Scrape all threads from library using cache-aware strategy.

        This method implements smart caching:
        1. Check if cache exists and covers requested date range
        2. If cache covers range: use cache only (fast path)
        3. If cache doesn't cover range: fetch gap from API only
        4. Merge cached + fetched threads (dedup by URL)
        5. Filter by requested date range
        6. Update cache with filtered threads only

        Args:
            from_date: Start date for filtering (YYYY-MM-DD format), inclusive
            to_date: End date for filtering (YYYY-MM-DD format), inclusive
            progress_callback: Optional callback function for progress updates

        Returns:
            List of ThreadRecord objects sorted by creation date (newest first)

        Raises:
            RuntimeError: If API request fails
            PerplexityHTTPStatusError: If API returns error status
            ValueError: If from_date or to_date is not a valid date string
        """
        # Validate date format before proceeding
        _validate_date_params(from_date, to_date)

        # Try cache-only fast path
        cached_result = self._try_cache_only(from_date, to_date)
        if cached_result is not None:
            return cached_result

        # Load existing cached threads and determine fetch range
        threads, fetch_from, _fetch_to = self._prepare_fetch(from_date, to_date)

        # Fetch from API and merge
        return await self._fetch_and_merge(
            from_date, to_date, fetch_from, threads, progress_callback
        )

    def _load_cached_threads(self) -> list[ThreadRecord]:
        """Load threads from the cache manager.

        Returns:
            List of ThreadRecord objects, or empty list if cache is unavailable.
        """
        cache_data = self.cache_manager.load_cache() if self.cache_manager else None
        if not cache_data:
            return []
        return convert_cache_dicts_to_thread_records(cache_data.get("threads", []))

    def _try_cache_only(
        self, from_date: str | None, to_date: str | None
    ) -> list[ThreadRecord] | None:
        """Attempt to satisfy the request from cache alone.

        Returns:
            List of ThreadRecord if cache covers the range, or None if fresh data is needed.
        """
        if not self.cache_manager or self.force_refresh:
            return None

        needs_fresh, _, _ = self.cache_manager.requires_fresh_data(from_date, to_date)
        if needs_fresh:
            return None

        self.logger.info("Using cached threads (no fresh data needed)")
        threads = self._load_cached_threads()
        return self._filter_by_date_range(threads, from_date, to_date)

    def _prepare_fetch(
        self, from_date: str | None, to_date: str | None
    ) -> tuple[list[ThreadRecord], str | None, str | None]:
        """Load cached threads and determine the date range to fetch from API.

        Returns:
            Tuple of (cached_threads, fetch_from, fetch_to).
        """
        if self.force_refresh:
            self.logger.info("Force refresh enabled, ignoring cache")
            return [], from_date, to_date

        if not self.cache_manager:
            return [], from_date, to_date

        _, fetch_from, fetch_to = self.cache_manager.requires_fresh_data(from_date, to_date)
        self.logger.info("Cache gap detected, fetching %s to %s", fetch_from, fetch_to)
        return self._load_cached_threads(), fetch_from, fetch_to

    def _merge_and_save(
        self,
        from_date: str | None,
        to_date: str | None,
        cached_threads: list[ThreadRecord],
        fetched_threads: list[ThreadRecord],
    ) -> list[ThreadRecord]:
        """Merge fetched threads with cache, filter by date, and persist.

        Args:
            from_date: Requested start date or None.
            to_date: Requested end date or None.
            cached_threads: Previously cached threads.
            fetched_threads: Newly fetched threads from API.

        Returns:
            Final filtered list of ThreadRecord objects.
        """
        threads = self._merge_with_cache(cached_threads, fetched_threads)
        threads = self._filter_by_date_range(threads, from_date, to_date)

        if self.cache_manager:
            self.cache_manager.save_cache(threads)

        return threads

    def _merge_with_cache(
        self,
        cached_threads: list[ThreadRecord],
        fetched_threads: list[ThreadRecord],
    ) -> list[ThreadRecord]:
        """Merge cached and fetched threads, deduplicating by URL.

        Args:
            cached_threads: Previously cached threads.
            fetched_threads: Newly fetched threads from API.

        Returns:
            Merged list of threads.
        """
        if not cached_threads or not self.cache_manager:
            return fetched_threads
        merged = self.cache_manager.merge_threads(cached_threads, fetched_threads)
        self.logger.info("Merged to %s unique threads", len(merged))
        return merged

    async def _fetch_and_merge(  # nosemgrep: too-many-parameters
        self,
        from_date: str | None,
        to_date: str | None,
        fetch_from: str | None,
        cached_threads: list[ThreadRecord],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[ThreadRecord]:
        """Fetch threads from API, merge with cached, filter, and save.

        Returns:
            Final list of ThreadRecord objects.
        """
        session_token = extract_session_token(self.token)
        fetched_threads = await self._fetch_all_threads_from_api(
            session_token, progress_callback, from_date=fetch_from
        )
        self.logger.info("Fetched %s threads from API", len(fetched_threads))

        return self._merge_and_save(from_date, to_date, cached_threads, fetched_threads)

    async def _make_api_request(
        self, client: AsyncSession, headers: dict, cookies: dict, request_body: dict
    ) -> list[dict]:
        """Make a single paginated API request and return thread data.

        Args:
            client: The async HTTP session.
            headers: Request headers.
            cookies: Request cookies.
            request_body: JSON body with pagination parameters.

        Returns:
            List of thread dictionaries from the API response.

        Raises:
            AuthenticationError: If API returns 401.
            RateLimitError: If API returns 429.
            PerplexityRequestError: On network errors.
            UpstreamSchemaError: If response cannot be parsed.
        """
        try:
            return await self._execute_api_post(client, headers, cookies, request_body)
        except PerplexityHTTPStatusError as e:
            _handle_http_error(e)
            return []  # unreachable, satisfies type checker
        except RequestException as e:
            raise PerplexityRequestError(f"Network error while fetching threads: {e}") from e

    async def _execute_api_post(
        self, client: AsyncSession, headers: dict, cookies: dict, request_body: dict
    ) -> list[dict]:
        """Execute the HTTP POST and parse the response.

        Args:
            client: The async HTTP session.
            headers: Request headers.
            cookies: Request cookies.
            request_body: JSON body with pagination parameters.

        Returns:
            Parsed list of thread dictionaries.

        Raises:
            PerplexityHTTPStatusError: If response is not OK.
            UpstreamSchemaError: If response cannot be parsed.
        """
        if self.rate_limiter:
            wait_time = await self.rate_limiter.acquire()
            if wait_time > 0:
                self.logger.debug("Rate limited: waited %ss", round(wait_time, 2))

        response = await client.post(
            f"{self.api_url}?version={self.api_version}&source=default",
            headers=headers,
            cookies=to_curl_cffi_cookies(cookies),
            json=request_body,
        )

        if not response.ok:
            raise_http_status_error(response)

        try:
            return parse_thread_list_payload(response.json())
        except ValueError as e:
            raise UpstreamSchemaError("Malformed thread list response from upstream API") from e

    def _build_auth_context(self, session_token: str) -> tuple[dict, dict]:
        """Build headers and cookies for API requests.

        Args:
            session_token: The authentication session token.

        Returns:
            Tuple of (headers, cookies).
        """
        headers = {"Content-Type": "application/json"}
        cookies = dict(self.cookies or {})
        cookies.setdefault("__Secure-next-auth.session-token", session_token)
        return headers, cookies

    async def _fetch_all_threads_from_api(
        self,
        session_token: str,
        progress_callback: Callable[[int, int], None] | None = None,
        from_date: str | None = None,
    ) -> list[ThreadRecord]:
        """Fetch all threads by paginating through the API endpoint.

        When from_date is provided, implements client-side filtering to avoid
        re-fetching previously cached threads. This enables smart partial updates
        where only the date gap is fetched from the API.

        Args:
            session_token: Authentication token
            progress_callback: Optional callback for progress updates
            from_date: Optional start date (YYYY-MM-DD) for partial fetches
            to_date: Optional end date (YYYY-MM-DD) for partial fetches

        Returns:
            List of ThreadRecord objects

        Raises:
            RuntimeError: If API request fails
            PerplexityHTTPStatusError: If API returns error status
        """
        threads: list[ThreadRecord] = []
        offset = 0
        limit = 100
        headers, cookies = self._build_auth_context(session_token)

        async with _create_async_session(timeout=30) as client:
            while True:
                request_body = {
                    "limit": limit,
                    "ascending": False,
                    "offset": offset,
                    "search_term": "",
                }
                self.logger.debug("Fetching threads: offset=%s, limit=%s", offset, limit)

                thread_data = await self._make_api_request(client, headers, cookies, request_body)
                if not thread_data:
                    break

                if self._process_thread_batch(
                    thread_data, threads, from_date, None, progress_callback
                ):
                    break

                if not _has_more_pages(thread_data):
                    break

                offset += limit

        return threads

    def _process_thread_batch(  # nosemgrep: too-many-parameters
        self,
        thread_data: list[dict],
        threads: list[ThreadRecord],
        from_date: str | None,
        total_threads: int | None,
        progress_callback: Callable[[int, int], None] | None,
    ) -> bool:
        """Process a batch of thread dicts, appending records to threads list.

        Args:
            thread_data: Raw thread dictionaries from API.
            threads: Accumulator list to append parsed records to.
            from_date: Optional lower date bound for early stopping.
            total_threads: Known total thread count (for progress reporting).
            progress_callback: Optional progress callback.

        Returns:
            True if fetching should stop (from_date cutoff reached).
        """
        for thread_dict in thread_data:
            stopped = self._process_single_thread_entry(thread_dict, threads, from_date)
            if stopped:
                return True

        _report_progress(progress_callback, len(threads), total_threads)
        return False

    def _process_single_thread_entry(
        self,
        thread_dict: dict,
        threads: list[ThreadRecord],
        from_date: str | None,
    ) -> bool:
        """Parse and append a single thread entry.

        Args:
            thread_dict: Raw thread dictionary.
            threads: Accumulator list.
            from_date: Optional lower date bound.

        Returns:
            True if fetching should stop.
        """
        try:
            record, should_stop = _parse_single_thread(thread_dict, from_date)
            if should_stop:
                return True
            if record:
                threads.append(record)
        except ValueError as e:
            raise UpstreamSchemaError("Malformed thread timestamp in upstream API response") from e
        return False

    def _filter_by_date_range(
        self,
        threads: list[ThreadRecord],
        from_date: str | None,
        to_date: str | None,
    ) -> list[ThreadRecord]:
        """Filter threads by date range.

        Args:
            threads: List of ThreadRecord objects
            from_date: Start date (YYYY-MM-DD), inclusive
            to_date: End date (YYYY-MM-DD), inclusive

        Returns:
            Filtered list of ThreadRecord objects
        """
        if not from_date and not to_date:
            return threads

        filtered = []
        for thread in threads:
            # Parse ISO 8601 timestamp back to datetime
            dt = datetime.fromisoformat(thread.created_at.replace("Z", "+00:00"))

            if is_in_date_range(dt, from_date, to_date):
                filtered.append(thread)

        return filtered
