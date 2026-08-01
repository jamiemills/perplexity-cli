"""Thread scraping functionality for Perplexity.ai library.

This module handles automated extraction of thread data from the Perplexity.ai
API endpoint using stored authentication token. Supports local encrypted caching
for efficient repeated exports.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Final,
    Protocol,
    TypedDict,
    TypeGuard,
    Unpack,
    cast,
    runtime_checkable,
)

from perplexity_cli.envelope import ErrorCode
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.threads.pagination import (
    _LEGACY_CONTEXT_ARG_LIMIT,
    _PROGRESS_CALLBACK_ARG_INDEX,
    _THREAD_PAGE_SIZE,
    _TOTAL_THREADS_ARG_INDEX,
    BatchProcessingContext,
    PaginationState,
    ProgressCallback,
    ThreadPayload,
    _build_batch_processing_context,
    _build_legacy_batch_processing_context,
    _coerce_optional_int,
    _coerce_optional_str,
    _coerce_progress_callback,
    _extract_total_threads,
    _has_more_pages,
    _is_in_date_range,
    _is_progress_callback,
    _legacy_context_value,
    _next_pagination_offset,
    _page_signature,
    _report_progress,
    _to_iso8601,
    _validate_batch_processing_arg_count,
    _validate_date_params,
)
from perplexity_cli.utils import session_factory
from perplexity_cli.utils.config import get_perplexity_base_url, get_thread_list_url
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.exceptions import (
    AuthenticationError,
    PerplexityHTTPStatusError,
    PerplexityRequestError,
    RateLimitError,
    UpstreamSchemaError,
)
from perplexity_cli.utils.http_errors import classify_http_error, raise_http_status_error
from perplexity_cli.utils.logging import get_logger
from perplexity_cli.utils.session_token import extract_session_token
from perplexity_cli.utils.upstream_contracts import (
    parse_thread_list_payload,
    require_list,
    require_mapping,
)
from perplexity_cli.utils.version import get_api_version

if TYPE_CHECKING:
    from curl_cffi.requests import AsyncSession
    from curl_cffi.requests.models import Response

# Helpers extracted to ``threads.pagination`` are re-exported here so the
# scraper's domain-test API (including the mutation test suite) stays stable.
__all__ = [
    "_LEGACY_CONTEXT_ARG_LIMIT",
    "_PROGRESS_CALLBACK_ARG_INDEX",
    "_THREAD_PAGE_SIZE",
    "_TOTAL_THREADS_ARG_INDEX",
    "BatchProcessingContext",
    "PaginationState",
    "ProgressCallback",
    "ThreadPayload",
    "_build_batch_processing_context",
    "_build_legacy_batch_processing_context",
    "_coerce_optional_int",
    "_coerce_optional_str",
    "_coerce_progress_callback",
    "_extract_total_threads",
    "_has_more_pages",
    "_is_in_date_range",
    "_is_progress_callback",
    "_legacy_context_value",
    "_next_pagination_offset",
    "_page_signature",
    "_report_progress",
    "_to_iso8601",
    "_validate_batch_processing_arg_count",
    "_validate_date_params",
]


def _load_request_exception_type() -> tuple[type[Exception], bool]:
    """Load the curl_cffi network exception type when available."""
    try:
        # Kept function-local: curl_cffi is a native library that may fail to
        # load on unsupported platforms, so the import must remain guarded
        # inside this try/except rather than moved to module top level.
        from curl_cffi.requests.exceptions import (
            RequestException,  # optional dependency (curl_cffi)
        )

        return RequestException, True
    except ImportError:  # pragma: no cover  # owner: quality-infrastructure; reason: optional native dependency fallback branch
        return Exception, False


_curl_request_exception_type, _CURL_CFFI_AVAILABLE = _load_request_exception_type()

# ---------------------------------------------------------------------------
# Module-level utility functions (extracted from ThreadScraper)
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_SECONDS: Final = 30


class RateLimiterProtocol(Protocol):
    """Minimal rate-limiter interface used by the scraper."""

    async def acquire(self) -> float:
        """Wait for permission to issue the next request."""
        ...


class ThreadCacheManagerProtocol(Protocol):
    """Minimal cache-manager interface used by the scraper."""

    def load_cache(self) -> dict[str, object] | None:
        """Load cached thread data if available."""
        ...

    def requires_fresh_data(
        self, from_date: str | None, to_date: str | None
    ) -> tuple[bool, str | None, str | None]:
        """Return whether the requested range requires fresh API data."""
        ...

    def save_cache(self, threads: list[ThreadRecord]) -> None:
        """Persist the supplied thread records to cache."""
        ...

    def merge_threads(
        self, cached_threads: list[ThreadRecord], fetched_threads: list[ThreadRecord]
    ) -> list[ThreadRecord]:
        """Merge cached and freshly fetched thread records."""
        ...


@runtime_checkable
class ResponseProtocol(Protocol):
    """Minimal response interface used by the scraper."""

    ok: bool
    url: object
    status_code: int
    headers: object
    content: object

    def json(self) -> object:
        """Return the decoded JSON payload."""
        ...


class _ResponseCandidateProtocol(Protocol):
    """Unvalidated response members inspected by the runtime guard."""

    ok: object
    status_code: object
    json: object


def _response_core_members(response: object) -> tuple[object, object] | None:
    """Read response members required for every HTTP outcome."""
    response_candidate = cast(_ResponseCandidateProtocol, response)
    try:
        return response_candidate.ok, response_candidate.json
    except AttributeError:
        return None


def _has_integer_status_code(response: object) -> bool:
    """Return whether a response exposes an integer status code."""
    response_candidate = cast(_ResponseCandidateProtocol, response)
    try:
        return isinstance(response_candidate.status_code, int)
    except AttributeError:
        return False


def _is_response_protocol(response: object) -> TypeGuard[ResponseProtocol]:
    """Return True when an object exposes the response attributes we rely on."""
    core_members = _response_core_members(response)
    if core_members is None:
        return False
    ok_value, json_method = core_members
    if not isinstance(ok_value, bool) or not callable(json_method):
        return False
    if ok_value:
        return True
    return _has_integer_status_code(response)


def _get_cache_str_field(thread_dict: dict[str, object], field: str) -> str:
    """Extract a required string field from a cached thread entry."""
    value = thread_dict.get(field)
    if not isinstance(value, str):
        msg = f"Malformed cached thread record: missing {field}"
        raise UpstreamSchemaError(msg)
    return value


def _convert_cache_thread_dicts(thread_dicts: list[dict[str, object]]) -> list[ThreadRecord]:
    """Proxy cache conversion through the shared thread utility helper."""
    records: list[ThreadRecord] = []
    for thread_dict in thread_dicts:
        records.append(
            ThreadRecord(
                title=_get_cache_str_field(thread_dict, "title"),
                url=_get_cache_str_field(thread_dict, "url"),
                created_at=_get_cache_str_field(thread_dict, "created_at"),
            )
        )
    return records


def _extract_cache_thread_dicts(raw_threads: object) -> list[dict[str, object]]:
    """Validate and normalise cached thread entries to string-key dictionaries."""
    raw_entries = require_list(raw_threads, "Malformed cached thread records")
    validated_entries: list[dict[str, object]] = []
    for entry_obj in raw_entries:
        entry_mapping = require_mapping(entry_obj, "Malformed cached thread records")
        validated_entry: dict[str, object] = {}
        for key, value in entry_mapping.items():
            validated_entry[key] = value
        validated_entries.append(validated_entry)

    return validated_entries


class ThreadScraperOptions(TypedDict, total=False):
    """Optional constructor keyword arguments for ``ThreadScraper``."""

    cookies: dict[str, str] | None
    rate_limiter: RateLimiterProtocol | None
    cache_manager: ThreadCacheManagerProtocol | None
    force_refresh: bool


@dataclass(frozen=True, slots=True)
class FetchMergeContext:
    """Parameters required to fetch fresh threads and merge them into cache."""

    from_date: str | None
    to_date: str | None
    fetch_from: str | None
    cached_threads: list[ThreadRecord]
    progress_callback: ProgressCallback | None


def _require_response(response: object) -> ResponseProtocol:
    """Validate that an upstream response matches the scraper protocol."""
    if isinstance(response, ResponseProtocol) or _is_response_protocol(response):
        return response
    msg = "Malformed HTTP response object from upstream session"
    raise UpstreamSchemaError(msg)


def _create_async_session(timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> AsyncSession[Response]:
    """Create an AsyncSession with Chrome TLS impersonation.

    Args:
        timeout: Request timeout in seconds.

    Returns:
        An AsyncSession configured for Chrome impersonation.

    Raises:
        RuntimeError: If curl_cffi is not installed.
    """
    if not _CURL_CFFI_AVAILABLE:
        msg = "curl_cffi is required but could not be imported"
        raise RuntimeError(msg)

    async_session_cls = session_factory.AsyncSession
    if async_session_cls is None:
        msg = "AsyncSession from session_factory resolved to None"
        raise RuntimeError(msg)

    return async_session_cls(impersonate="chrome", timeout=timeout)


def _get_str_field(thread_dict: ThreadPayload, field: str, default: str | None = None) -> str:
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
        msg = f"Malformed thread {field} in upstream API response"
        raise UpstreamSchemaError(msg)
    return value


def _parse_single_thread(
    thread_dict: ThreadPayload, from_date: str | None
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
        msg = "Malformed thread timestamp in upstream API response"
        raise UpstreamSchemaError(msg)

    dt = datetime.fromisoformat(timestamp_str)
    if from_date and not _is_in_date_range(dt, from_date, None):
        return None, True

    slug = _get_str_field(thread_dict, "slug", "")
    title = _get_str_field(thread_dict, "title", "Untitled")
    url = f"{get_perplexity_base_url()}/search/{slug}"
    return ThreadRecord(
        title=title,
        url=url,
        created_at=_to_iso8601(dt),
    ), False


def _handle_http_error(e: PerplexityHTTPStatusError) -> None:
    """Re-raise HTTP status errors as domain-specific exceptions.

    Args:
        e: The HTTP status error to handle.

    Raises:
        AuthenticationError: If status is 401.
        RateLimitError: If status is 429.
        PerplexityHTTPStatusError: For all other statuses.
    """
    error_code, _, _ = classify_http_error(e)
    if error_code == ErrorCode.authentication_required:
        msg = (
            "Authentication failed. Token may be expired. "
            "Please re-authenticate with: perplexity-cli auth"
        )
        raise AuthenticationError(msg) from e
    if error_code == ErrorCode.rate_limited:
        msg = "Rate limit exceeded while fetching threads. Please try again later."
        raise RateLimitError(msg) from e
    raise PerplexityHTTPStatusError(str(e), response=e.response) from e


class ThreadScraper:
    """Scraper for extracting thread data from Perplexity.ai library.

    This class uses the /rest/thread/list_ask_threads API endpoint to fetch
    thread metadata including creation timestamps using the stored auth token.
    """

    def __init__(
        self,
        token: str,
        **options: Unpack[ThreadScraperOptions],
    ) -> None:
        """Initialise thread scraper.

        Args:
            token: Authentication token (from TokenManager)
            **options: Optional browser cookies, rate limiter, cache manager,
                and force-refresh flag.
        """
        cookies = options.get("cookies")
        rate_limiter = options.get("rate_limiter")
        cache_manager = options.get("cache_manager")
        force_refresh = options.get("force_refresh", False)
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
        progress_callback: ProgressCallback | None = None,
    ) -> list[ThreadRecord]:
        """Scrape all threads from library using cache-aware strategy.

        This method implements smart caching:
        1. Check if cache exists and covers requested date range
        2. If cache covers range: use cache only (fast path)
        3. If cache doesn't cover range: fetch gap from API only
        4. Merge cached + fetched threads (dedup by URL)
        5. Persist the complete merged known set to cache
        6. Filter the returned result by the requested date range

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
            FetchMergeContext(
                from_date=from_date,
                to_date=to_date,
                fetch_from=fetch_from,
                cached_threads=threads,
                progress_callback=progress_callback,
            )
        )

    def _load_cached_threads(self) -> list[ThreadRecord]:
        """Load threads from the cache manager.

        Returns:
            List of ThreadRecord objects, or empty list if cache is unavailable.
        """
        cache_data = self.cache_manager.load_cache() if self.cache_manager else None
        if not cache_data:
            return []
        thread_dicts = _extract_cache_thread_dicts(cache_data.get("threads", []))
        return _convert_cache_thread_dicts(thread_dicts)

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
        """Merge fetched threads with cache, persist the full set, and filter.

        The complete merged known set is persisted so that narrow exports never
        delete broader cached history. The date range is applied only to the
        returned view.

        Args:
            from_date: Requested start date or None.
            to_date: Requested end date or None.
            cached_threads: Previously cached threads.
            fetched_threads: Newly fetched threads from API.

        Returns:
            Final date-filtered list of ThreadRecord objects.
        """
        merged = self._merge_with_cache(cached_threads, fetched_threads)

        if self.cache_manager:
            self.cache_manager.save_cache(merged)

        return self._filter_by_date_range(merged, from_date, to_date)

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

    async def _fetch_and_merge(self, context: FetchMergeContext) -> list[ThreadRecord]:
        """Fetch threads from API, merge with cached, filter, and save.

        Returns:
            Final list of ThreadRecord objects.
        """
        session_token = extract_session_token(self.token)
        fetched_threads = await self._fetch_all_threads_from_api(
            session_token, context.progress_callback, from_date=context.fetch_from
        )
        self.logger.info("Fetched %s threads from API", len(fetched_threads))

        return self._merge_and_save(
            context.from_date,
            context.to_date,
            context.cached_threads,
            fetched_threads,
        )

    async def _make_api_request(
        self,
        client: AsyncSession[Response],
        headers: dict[str, str],
        cookies: dict[str, str],
        request_body: ThreadPayload,
    ) -> list[ThreadPayload]:
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
        return await self._execute_api_post(client, headers, cookies, request_body)

    async def _execute_api_post(
        self,
        client: AsyncSession[Response],
        headers: dict[str, str],
        cookies: dict[str, str],
        request_body: ThreadPayload,
    ) -> list[ThreadPayload]:
        """Execute the HTTP POST and parse the response.

        Args:
            client: The async HTTP session.
            headers: Request headers.
            cookies: Request cookies.
            request_body: JSON body with pagination parameters.

        Returns:
            Parsed list of thread dictionaries.

        Raises:
            AuthenticationError: If API returns 401.
            RateLimitError: If API returns 429.
            PerplexityHTTPStatusError: If API returns any other error status.
            PerplexityRequestError: On network errors.
            UpstreamSchemaError: If response cannot be parsed.
        """
        await self._acquire_rate_limit()
        try:
            response = await self._post_thread_list_request(client, headers, cookies, request_body)
        except _curl_request_exception_type as e:
            msg = f"Network error while fetching threads: {e}"
            raise PerplexityRequestError(msg) from e
        return self._handle_thread_list_response(response)

    async def _acquire_rate_limit(self) -> None:
        """Wait on the rate limiter if one is configured.

        Args:
            None.

        Returns:
            None.
        """
        if not self.rate_limiter:
            return
        wait_time = await self.rate_limiter.acquire()
        if wait_time > 0:
            self.logger.debug("Rate limited: waited %ss", round(wait_time, 2))

    async def _post_thread_list_request(
        self,
        client: AsyncSession[Response],
        headers: dict[str, str],
        cookies: dict[str, str],
        request_body: ThreadPayload,
    ) -> ResponseProtocol:
        """POST the thread-list request and validate the response object.

        Args:
            client: The async HTTP session.
            headers: Request headers.
            cookies: Request cookies.
            request_body: JSON body with pagination parameters.

        Returns:
            The validated response object.

        Raises:
            UpstreamSchemaError: If the response object is malformed.
        """
        return _require_response(
            await client.post(
                f"{self.api_url}?version={self.api_version}&source=default",
                headers=headers,
                cookies=to_curl_cffi_cookies(cookies),
                json=dict(request_body),
            )
        )

    def _handle_thread_list_response(self, response: ResponseProtocol) -> list[ThreadPayload]:
        """Convert a non-OK status or parse the thread-list payload.

        Args:
            response: The validated HTTP response object.

        Returns:
            Parsed list of thread dictionaries.

        Raises:
            AuthenticationError: If API returns 401.
            RateLimitError: If API returns 429.
            PerplexityHTTPStatusError: If API returns any other error status.
            UpstreamSchemaError: If response payload cannot be parsed.
        """
        if not response.ok:
            try:
                raise_http_status_error(response)
            except PerplexityHTTPStatusError as e:
                _handle_http_error(e)

        try:
            return parse_thread_list_payload(response.json())
        except ValueError as e:
            msg = "Malformed thread list response from upstream API"
            raise UpstreamSchemaError(msg) from e

    def _build_auth_context(self, session_token: str) -> tuple[dict[str, str], dict[str, str]]:
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
        progress_callback: ProgressCallback | None = None,
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
            AuthenticationError: If API returns 401.
            RateLimitError: If API returns 429.
            PerplexityRequestError: On network errors.
            PerplexityHTTPStatusError: If API returns any other error status.
            UpstreamSchemaError: If a payload is malformed, the pagination
                offset does not advance, or a repeated page signature is seen.
        """
        threads: list[ThreadRecord] = []
        state = PaginationState()
        headers, cookies = self._build_auth_context(session_token)
        batch_context = BatchProcessingContext(
            from_date=from_date,
            total_threads=None,
            progress_callback=progress_callback,
        )

        async with _create_async_session(timeout=_DEFAULT_TIMEOUT_SECONDS) as client:
            while True:
                request_body: ThreadPayload = {
                    "limit": state.limit,
                    "ascending": False,
                    "offset": state.offset,
                    "search_term": "",
                }
                self.logger.debug(
                    "Fetching threads: offset=%s, limit=%s", state.offset, state.limit
                )

                thread_data = await self._make_api_request(client, headers, cookies, request_body)
                if not thread_data:
                    break

                state, continue_pagination = self._process_page(
                    thread_data,
                    threads,
                    state,
                    batch_context,
                )
                if not continue_pagination:
                    break

        return threads

    def _process_page(
        self,
        thread_data: list[ThreadPayload],
        threads: list[ThreadRecord],
        state: PaginationState,
        context: BatchProcessingContext,
    ) -> tuple[PaginationState, bool]:
        """Validate and process one page, computing the next pagination state.

        Guards against repeated page signatures and non-advancing offsets,
        which would otherwise cause an infinite pagination loop.

        Args:
            thread_data: Raw thread dictionaries from the current page.
            threads: Accumulator list to append parsed records to.
            state: Current pagination cursor state.
            context: Batch processing context.

        Returns:
            Tuple of (next_state, continue_pagination).

        Raises:
            UpstreamSchemaError: If the page signature repeats or the offset
                would not advance.
        """
        signature = _page_signature(thread_data)
        if state.previous_signature is not None and signature == state.previous_signature:
            msg = "Repeated page signature in upstream pagination response"
            raise UpstreamSchemaError(msg)

        should_stop = self._process_thread_batch(thread_data, threads, context)
        if should_stop or not _has_more_pages(thread_data):
            return replace(state, previous_signature=signature), False

        next_offset = _next_pagination_offset(state.offset, state.limit)
        return replace(state, offset=next_offset, previous_signature=signature), True

    def _process_thread_batch(
        self,
        thread_data: list[ThreadPayload],
        threads: list[ThreadRecord],
        *context_args: object,
    ) -> bool:
        """Process a batch of thread dicts, appending records to threads list.

        Args:
            thread_data: Raw thread dictionaries from API.
            threads: Accumulator list to append parsed records to.
            *context_args: Either a single ``BatchProcessingContext`` or the
                legacy ``from_date``, ``total_threads``, ``progress_callback`` trio.

        Returns:
            True if fetching should stop (from_date cutoff reached).
        """
        context = _build_batch_processing_context(*context_args)
        for thread_dict in thread_data:
            stopped = self._process_single_thread_entry(thread_dict, threads, context.from_date)
            if stopped:
                return True

        total_threads = context.total_threads
        if thread_data:
            total_threads = _extract_total_threads(thread_data[0], total_threads)
        _report_progress(context.progress_callback, len(threads), total_threads)
        return False

    def _process_single_thread_entry(
        self,
        thread_dict: ThreadPayload,
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
            msg = "Malformed thread timestamp in upstream API response"
            raise UpstreamSchemaError(msg) from e
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

        filtered: list[ThreadRecord] = []
        for thread in threads:
            # Parse ISO 8601 timestamp back to datetime
            dt = datetime.fromisoformat(thread.created_at)

            if _is_in_date_range(dt, from_date, to_date):
                filtered.append(thread)

        return filtered
