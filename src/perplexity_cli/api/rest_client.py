"""Non-streaming REST client for Perplexity API endpoints.

Provides a simple JSON GET/POST interface using curl_cffi with Chrome
TLS fingerprint impersonation, sharing the session factory and header
construction with the SSE streaming client.
"""

from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from curl_cffi.requests import Session

from perplexity_cli.auth.models import AuthContext
from perplexity_cli.utils.cookies import to_curl_cffi_cookies
from perplexity_cli.utils.http_errors import raise_http_status_error
from perplexity_cli.utils.http_headers import build_perplexity_headers
from perplexity_cli.utils.logging import get_logger


class RestClient:
    """Non-streaming HTTP client for Perplexity REST endpoints.

    Uses curl_cffi with Chrome TLS fingerprint impersonation to bypass
    Cloudflare's bot protection, sharing the same session factory as
    the SSE streaming client.
    """

    def __init__(
        self,
        auth: AuthContext,
        timeout: int | None = None,
    ) -> None:
        """Initialise REST client.

        Args:
            auth: Authentication credentials (token and optional cookies).
            timeout: Request timeout in seconds (default from config).
        """
        self.auth = auth
        self.timeout = timeout
        self.logger = get_logger()
        self._client: Session | None = None

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests.

        Returns:
            Dictionary of HTTP headers including authentication.
        """
        return build_perplexity_headers(
            self.auth.token,
            self.auth.cookies,
            accept="application/json",
        )

    def _get_client(self) -> Session:
        """Get or create the persistent curl_cffi session.

        Returns:
            The shared Session instance with Chrome TLS impersonation.

        Raises:
            RuntimeError: If curl_cffi is not installed.
        """
        if self._client is None:
            from perplexity_cli.utils.session_factory import create_sync_session

            self._client = create_sync_session(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the persistent session if open."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> RestClient:
        """Enter context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit context manager, closing the HTTP client."""
        self.close()

    def get_json(self, url: str) -> Any:
        """Perform a GET request and return the parsed JSON response.

        Args:
            url: The API endpoint URL.

        Returns:
            Parsed JSON response body.

        Raises:
            PerplexityHTTPStatusError: For HTTP errors (401, 403, 429, etc.).
            PerplexityRequestError: For network/connection errors.
        """
        headers = self.get_headers()
        cookies = to_curl_cffi_cookies(self.auth.cookies)
        client = self._get_client()

        self.logger.debug("REST GET %s", url)
        response = client.get(
            url,
            headers=headers,
            cookies=cookies,
            timeout=self.timeout,
        )

        if not response.ok:
            raise_http_status_error(response)

        return response.json()
