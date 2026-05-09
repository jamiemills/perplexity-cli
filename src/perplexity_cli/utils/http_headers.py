"""Shared HTTP header construction for Perplexity API requests.

Both the SSE query client and the attachment uploader need the same set
of headers (Authorization, Content-Type, Origin, Referer, X-CSRFToken).
This module provides a single function so changes to the header contract
only need to be made in one place.
"""

from __future__ import annotations


def build_perplexity_headers(
    token: str | None,
    cookies: dict[str, str] | None = None,
    *,
    content_type: str = "application/json",
    accept: str | None = None,
    base_url: str | None = None,
) -> dict[str, str]:
    """Build standard HTTP headers for Perplexity API requests.

    curl_cffi sets ``User-Agent`` automatically based on the impersonated
    browser, so it is not included here.  Cookies are passed separately
    via the ``cookies`` parameter on requests rather than as a header.

    Args:
        token: Optional JWT authentication token.
        cookies: Optional browser cookies; used to extract the CSRF token.
        content_type: Value for the ``Content-Type`` header.
        accept: Optional value for the ``Accept`` header.
        base_url: Perplexity base URL used for Origin/Referer headers.
            When ``None`` the value is loaded from configuration.

    Returns:
        Dictionary of HTTP headers.
    """
    if base_url is None:
        from perplexity_cli.utils.config import get_perplexity_base_url

        base_url = get_perplexity_base_url()

    headers: dict[str, str] = {
        "Content-Type": content_type,
        "Origin": base_url,
        "Referer": base_url.rstrip("/") + "/",
    }

    if accept:
        headers["Accept"] = accept

    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Add CSRF token from cookies if available
    if cookies and "csrftoken" in cookies:
        headers["X-CSRFToken"] = cookies["csrftoken"]

    return headers
