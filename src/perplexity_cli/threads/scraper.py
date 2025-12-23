"""Thread scraping functionality for Perplexity.ai library.

This module handles automated extraction of thread data from the Perplexity.ai
API endpoint using stored authentication token.
"""

import json
from datetime import datetime
from typing import Any, Optional

import httpx

from perplexity_cli.threads.date_parser import is_in_date_range, to_iso8601
from perplexity_cli.threads.exporter import ThreadRecord
from perplexity_cli.utils.logging import get_logger
from perplexity_cli.utils.rate_limiter import RateLimiter


class ThreadScraper:
    """Scraper for extracting thread data from Perplexity.ai library.

    This class uses the /rest/thread/list_ask_threads API endpoint to fetch
    thread metadata including creation timestamps using the stored auth token.
    """

    def __init__(self, token: str, rate_limiter: Optional[RateLimiter] = None) -> None:
        """Initialise thread scraper.

        Args:
            token: Authentication token (from TokenManager)
            rate_limiter: Optional RateLimiter instance for request throttling
        """
        self.token = token
        self.rate_limiter = rate_limiter
        self.logger = get_logger()
        self.api_url = "https://www.perplexity.ai/rest/thread/list_ask_threads"
        self.api_version = "2.18"

    async def scrape_all_threads(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        progress_callback: Any = None,
    ) -> list[ThreadRecord]:
        """Scrape all threads from library using the API endpoint.

        This method:
        1. Calls the /rest/thread/list_ask_threads API endpoint with stored token
        2. Paginates through all results
        3. Extracts timestamps from the API response
        4. Filters by date range if specified
        5. Returns list of ThreadRecord objects

        Args:
            from_date: Start date for filtering (YYYY-MM-DD format), inclusive
            to_date: End date for filtering (YYYY-MM-DD format), inclusive
            progress_callback: Optional callback function for progress updates

        Returns:
            List of ThreadRecord objects sorted by creation date (newest first)

        Raises:
            RuntimeError: If API request fails
            httpx.HTTPStatusError: If API returns error status
        """
        self.logger.info("Starting thread scraping via API endpoint...")

        # Parse token to get session cookie
        try:
            token_data = json.loads(self.token)
            # Token is stored as NextAuth.js session data
            # We need to extract the session token
            session_token = token_data.get("user", {}).get("accessToken")
            if not session_token:
                # Try alternative structure
                session_token = self.token
        except json.JSONDecodeError:
            # Token might be a raw string
            session_token = self.token

        # Fetch all threads via API
        threads = await self._fetch_all_threads_from_api(session_token, progress_callback)
        self.logger.info(f"Fetched {len(threads)} threads from API")

        # Filter by date range if specified
        if from_date or to_date:
            filtered = self._filter_by_date_range(threads, from_date, to_date)
            self.logger.info(
                f"Filtered to {len(filtered)} threads "
                f"(from_date={from_date}, to_date={to_date})"
            )
            return filtered

        return threads

    async def _fetch_all_threads_from_api(
        self, session_token: str, progress_callback: Any = None
    ) -> list[ThreadRecord]:
        """Fetch all threads by paginating through the API endpoint.

        Args:
            session_token: Authentication token
            progress_callback: Optional callback for progress updates

        Returns:
            List of ThreadRecord objects

        Raises:
            RuntimeError: If API request fails
            httpx.HTTPStatusError: If API returns error status
        """
        threads = []
        offset = 0
        limit = 100  # Fetch 100 threads per request
        total_threads = None

        # Build headers with authentication
        headers = {
            "Content-Type": "application/json",
            "Cookie": f"__Secure-next-auth.session-token={session_token}",
            "User-Agent": "perplexity-cli",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                # Prepare API request body
                request_body = {
                    "limit": limit,
                    "ascending": False,  # Newest first
                    "offset": offset,
                    "search_term": "",
                }

                self.logger.debug(f"Fetching threads: offset={offset}, limit={limit}")

                try:
                    # Make API request
                    response = await client.post(
                        f"{self.api_url}?version={self.api_version}&source=default",
                        headers=headers,
                        json=request_body,
                    )

                    # Check for errors
                    response.raise_for_status()

                    # Parse response
                    thread_data = response.json()

                    # Apply rate limiting after successful request
                    if self.rate_limiter:
                        wait_time = await self.rate_limiter.acquire()
                        if wait_time > 0:
                            self.logger.debug(f"Rate limited: waited {wait_time:.2f}s")

                    if not thread_data or len(thread_data) == 0:
                        # No more threads
                        break

                    # Extract thread records from API response
                    for thread_dict in thread_data:
                        try:
                            # Get total count from first response
                            if total_threads is None:
                                total_threads = thread_dict.get(
                                    "total_threads", len(thread_data)
                                )

                            # Extract timestamp
                            timestamp_str = thread_dict.get("last_query_datetime")
                            if not timestamp_str:
                                self.logger.warning(
                                    f"No timestamp for thread: {thread_dict.get('title', 'unknown')}"
                                )
                                continue

                            # Parse ISO 8601 timestamp
                            # API returns format like "2025-10-14T00:05:15.472548"
                            dt = datetime.fromisoformat(timestamp_str)

                            # Convert to ISO 8601 with Z suffix
                            iso_date = to_iso8601(dt)

                            # Build thread URL from slug
                            slug = thread_dict.get("slug", "")
                            url = f"https://www.perplexity.ai/search/{slug}"

                            # Get title
                            title = thread_dict.get("title", "Untitled")

                            threads.append(
                                ThreadRecord(title=title, url=url, created_at=iso_date)
                            )

                        except (ValueError, KeyError) as e:
                            self.logger.warning(f"Failed to parse thread data: {e}")
                            continue

                    # Progress callback
                    if progress_callback and total_threads:
                        progress_callback(len(threads), total_threads)

                    # Check if we have more pages
                    has_next_page = (
                        thread_data[0].get("has_next_page", False) if thread_data else False
                    )

                    if not has_next_page:
                        break

                    # Move to next page
                    offset += limit

                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401:
                        raise RuntimeError(
                            "Authentication failed. Token may be expired. "
                            "Please re-authenticate with: perplexity-cli auth"
                        ) from e
                    raise

        return threads

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
